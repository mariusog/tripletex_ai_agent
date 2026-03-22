"""Ledger/voucher handlers: create and reverse vouchers via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler
from src.handlers.entity_resolver import _resolve_supplier
from src.services.posting_builder import build_posting, merge_vat_postings, resolve_account

logger = logging.getLogger(__name__)

# Re-export for backward compatibility (bank.py, dimension.py, reporting.py)
_build_posting = build_posting
_resolve_account = resolve_account


@register_handler
class CreateSupplierHandler(BaseHandler):
    """POST /supplier with extracted fields. 1 API call."""

    tier = 2
    description = "Create a new supplier"
    param_schema = {
        "name": ParamSpec(description="Supplier name"),
        "organizationNumber": ParamSpec(required=False),
        "email": ParamSpec(required=False),
        "phoneNumber": ParamSpec(required=False),
        "postalAddress": ParamSpec(required=False, type="object"),
    }
    disambiguation = "Suppliers provide goods/services TO us. NOT create_customer."

    def get_task_type(self) -> str:
        return "create_supplier"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"name": params["name"]}
        for field in (
            "email",
            "phoneNumber",
            "phoneNumberMobile",
            "organizationNumber",
            "invoiceEmail",
            "description",
        ):
            if params.get(field):
                body[field] = params[field]
        if body.get("email") and not body.get("invoiceEmail"):
            body["invoiceEmail"] = body["email"]
        for addr_field in ("postalAddress", "physicalAddress"):
            if params.get(addr_field):
                addr = params[addr_field]
                if isinstance(addr, str):
                    body[addr_field] = {"addressLine1": addr}
                elif isinstance(addr, dict):
                    body[addr_field] = addr
        body = self.strip_none_values(body)
        result = api_client.post("/supplier", data=body)
        value = result.get("value", {})
        logger.info("Created supplier id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class CreateVoucherHandler(BaseHandler):
    """POST /ledger/voucher with debit/credit postings."""

    tier = 3
    description = "Create a voucher with debit/credit postings"
    param_schema = {
        "description": ParamSpec(description="Voucher description"),
        "date": ParamSpec(required=False, type="date"),
        "postings": ParamSpec(type="list", description="Debit/credit postings"),
        "supplier": ParamSpec(required=False, description="Supplier name or ref"),
        "invoiceNumber": ParamSpec(
            required=False,
            description="Supplier invoice/receipt number (fakturanr/kvitteringsnr)",
        ),
        "dueDate": ParamSpec(required=False, type="date"),
    }
    disambiguation = (
        "For supplier invoices and receipts, use this. "
        "Use 2 postings: debit expense account with GROSS amount (inkl MVA), "
        "credit 2400 with negative gross amount. Do NOT manually split VAT — "
        "Tripletex handles it via the account's VAT type. "
        "From receipts/PDFs: extract ALL fields: supplier name, org number, date, "
        "invoiceNumber, dueDate, GROSS amount (total inkl MVA). "
        "Choose expense account based on what was purchased: "
        "6300=rent/lokale, 6340=utilities, 6500=tools/verktøy, "
        "6540=inventory/furniture/kontorstoler/whiteboard, "
        "6800=office supplies/kontorrekvisita/papir, "
        "6700=accounting/audit, 6800=office supplies, 6860=IT/software, "
        "7000=travel, 7100=car/bilgodtgjørelse, 7140=transport/train/tog, "
        "7150=accommodation/overnatting, "
        "7350=representation/forretningslunsj/restaurant/meals, "
        "7300=marketing/sales. "
        "ALWAYS use NUMERIC account codes. "
        "CRITICAL: From PDF receipts, ALWAYS extract the receipt/invoice number "
        "(look for 'Fakturanr', 'Invoice No', 'Kvittering nr', 'Receipt #', etc.) "
        "and pass it as 'invoiceNumber'. Also put department on each posting."
    )

    def get_task_type(self) -> str:
        return "create_voucher"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        date_val = self.validate_date(params.get("date"), "date")
        if not date_val:
            date_val = dt_date.today().isoformat()

        body: dict[str, Any] = {"date": date_val}
        for field in ("description", "number", "tempNumber"):
            if field in params and params[field] is not None:
                body[field] = params[field]
        # Map supplier invoice number
        inv_num = params.get("invoiceNumber") or params.get("invoice_number")
        if inv_num:
            body["externalVoucherNumber"] = str(inv_num)

        supplier_ref = _resolve_supplier(api_client, params.get("supplier"))

        # For supplier invoices, set voucherType to "Leverandørfaktura"
        if supplier_ref or params.get("supplier") or params.get("has_attachments"):
            try:
                vt_resp = api_client.get_cached(
                    "supplier_voucher_type",
                    "/ledger/voucherType",
                    params={"count": 20},
                    fields="id,name",
                )
                for vt in vt_resp.get("values", []):
                    vt_name = (vt.get("name") or "").lower()
                    if "leverandør" in vt_name or "supplier" in vt_name:
                        body["voucherType"] = {"id": vt["id"]}
                        break
            except Exception:
                logger.debug("Could not look up supplier voucher type")

        customer_ref = None
        if params.get("customer"):
            from src.handlers.entity_resolver import resolve as _resolve_entity

            customer_ref = _resolve_entity(api_client, "customer", params["customer"])

        # If postings use account 1500 (receivable) but no customer, find one
        # Prefer customer with overdue invoices (for late fee tasks)
        if not customer_ref:
            needs_customer = any(
                1500 <= self._acct_num(p) <= 1599 for p in params.get("postings", [])
            )
            if needs_customer:
                try:
                    inv_resp = api_client.get(
                        "/invoice",
                        params={
                            "count": 20,
                            "invoiceDateFrom": "2020-01-01",
                            "invoiceDateTo": "2030-01-01",
                        },
                        fields="id,customer(id,name),amount,amountOutstanding",
                    )
                    invoices = inv_resp.get("values", [])
                    logger.info("Overdue search: found %d invoices", len(invoices))
                    for inv in invoices:
                        outstanding = inv.get("amountOutstanding") or 0
                        # If amountOutstanding not available, treat any invoice as candidate
                        if outstanding > 0 or (
                            inv.get("amount", 0) > 0 and "amountOutstanding" not in inv
                        ):
                            cust = inv.get("customer")
                            if cust and cust.get("id"):
                                customer_ref = {"id": cust["id"]}
                                params["customer"] = customer_ref
                                params["_overdue_invoice_id"] = inv["id"]
                                logger.info(
                                    "Found overdue invoice id=%s customer=%s",
                                    inv["id"],
                                    cust["id"],
                                )
                                break
                    # Fallback: use first invoice's customer
                    if not customer_ref and invoices:
                        cust = invoices[0].get("customer")
                        if cust and cust.get("id"):
                            customer_ref = {"id": cust["id"]}
                            params["customer"] = customer_ref
                            params["_overdue_invoice_id"] = invoices[0]["id"]
                            logger.info("Fallback to first invoice %s", invoices[0]["id"])
                    if not customer_ref:
                        resp = api_client.get("/customer", params={"count": 1}, fields="id")
                        vals = resp.get("values", [])
                        if vals:
                            customer_ref = {"id": vals[0]["id"]}
                            params["customer"] = customer_ref
                except Exception:
                    logger.exception("Failed finding customer for receivable")

        # Override tax amounts with actual P&L calculation
        raw_postings = params.get("postings", [])
        raw_postings = self._fix_tax_amounts(api_client, raw_postings, date_val)

        # Merge manual VAT split if present
        vat_rate = params.get("vatRate") or params.get("vat")
        raw_postings = merge_vat_postings(raw_postings, vat_rate)

        # Normalize debitAccount/creditAccount into separate rows
        postings: list[dict[str, Any]] = []
        for p in raw_postings:
            if "debitAccount" in p and "creditAccount" in p:
                amt = p.get("amount", p.get("amountGross", 0))
                if not amt:
                    # Try to infer amount from existing data for salary accruals
                    amt = self._infer_missing_amount(api_client, p)
                if not amt:
                    logger.warning("Skipping posting with no amount: %s", p)
                    continue
                postings.append(
                    {
                        "account": p["debitAccount"],
                        "debit": amt,
                        "description": p.get("description", ""),
                        "vatRate": p.get("vatRate") or vat_rate,
                    }
                )
                postings.append(
                    {
                        "account": p["creditAccount"],
                        "credit": amt,
                        "description": p.get("description", ""),
                    }
                )
            else:
                # Infer missing amount for salary accrual postings
                acct = p.get("account")
                amt = p.get("amount", p.get("amountGross", 0))
                if not amt and acct:
                    try:
                        acct_num = int(acct)
                    except (TypeError, ValueError):
                        acct_num = 0
                    if acct_num == 5000:
                        inferred = self._infer_missing_amount(
                            api_client, {"debitAccount": "5000", "creditAccount": "2900"}
                        )
                        if inferred:
                            p["amount"] = inferred
                    elif acct_num == 2900 and len(raw_postings) > 1:
                        # Find matching 5000 posting to get the same amount
                        for other in raw_postings:
                            other_acct = other.get("account")
                            if other_acct and str(other_acct) == "5000" and other.get("amount"):
                                p["amount"] = -abs(other["amount"])
                                break
                if vat_rate and "vatRate" not in p and "vatType" not in p:
                    p["vatRate"] = vat_rate
                postings.append(p)

        # Propagate top-level department to expense postings only (not AP/bank)
        top_dept = params.get("department")
        if top_dept and postings:
            for p in postings:
                if "department" not in p:
                    acct = p.get("account") or p.get("debitAccount") or ""
                    try:
                        acct_num = int(acct)
                    except (TypeError, ValueError):
                        acct_num = 0
                    # Only set department on expense/cost accounts (4000+)
                    if acct_num >= 4000:
                        p["department"] = top_dept

        if postings:
            built = []
            for i, p in enumerate(postings):
                posting = build_posting(api_client, p, row=i + 1, supplier=supplier_ref)
                acct = p.get("account") or p.get("debitAccount") or p.get("creditAccount")
                try:
                    acct_num = int(acct) if acct else 0
                except (TypeError, ValueError):
                    acct_num = 0
                if customer_ref and 1500 <= acct_num <= 1599:
                    posting["customer"] = customer_ref
                # Set invoice number on AP posting (2400)
                if inv_num and 2400 <= acct_num <= 2499:
                    posting["invoiceNumber"] = str(inv_num)
                built.append(posting)
            body["postings"] = built

        body = self.strip_none_values(body)
        logger.info("Voucher body: %s", body)
        result = api_client.post("/ledger/voucher", data=body, params={"sendToLedger": "true"})
        value = result.get("value", {})
        voucher_id = value.get("id")
        logger.info("Created voucher id=%s", voucher_id)

        # Read back to verify what was actually created
        if voucher_id and (supplier_ref or params.get("has_attachments")):
            try:
                verify = api_client.get(
                    f"/ledger/voucher/{voucher_id}",
                    fields="id,number,date,description,voucherType(id,name),"
                    "externalVoucherNumber,vendorInvoiceNumber,"
                    "postings(account(number),amountGross,supplier(id,name),"
                    "department(id,name),invoiceNumber,vatType(id))",
                )
                logger.info("Voucher verify: %s", verify.get("value", {}))
            except Exception:
                logger.debug("Could not verify voucher")
            # Check if it appears as a supplier invoice
            try:
                from datetime import date as _dt3
                from datetime import timedelta as _td

                si_resp = api_client.get(
                    "/supplierInvoice",
                    params={
                        "count": 5,
                        "voucherId": voucher_id,
                        "invoiceDateFrom": "2020-01-01",
                        "invoiceDateTo": (_dt3.today() + _td(days=365)).isoformat(),
                    },
                    fields="id,invoiceNumber,supplier(id,name),voucher(id),amount,amountCurrency",
                )
                si_vals = si_resp.get("values", [])
                logger.info(
                    "SupplierInvoice check: %d found, data=%s",
                    len(si_vals),
                    si_vals,
                )
            except Exception as e:
                logger.info("SupplierInvoice endpoint: %s", e)

        return {"id": voucher_id, "action": "created"}

    @staticmethod
    def _fix_tax_amounts(
        api_client: TripletexClient,
        postings: list[dict[str, Any]],
        date: str,
    ) -> list[dict[str, Any]]:
        """Override LLM tax amounts with actual P&L calculation.

        When postings include account 8700 (tax expense), compute the real
        taxable profit from the balance sheet and use 22% of that.
        """
        # Check if any posting targets tax accounts (8700-8799)
        has_tax = False
        for p in postings:
            acct = p.get("account") or p.get("debitAccount") or ""
            try:
                if 8700 <= int(acct) <= 8799:
                    has_tax = True
                    break
            except (TypeError, ValueError):
                continue

        if not has_tax:
            return postings

        # Compute actual taxable profit from balance sheet
        try:
            year = date[:4] if date else "2025"
            resp = api_client.get(
                "/balanceSheet",
                params={
                    "dateFrom": f"{year}-01-01",
                    "dateTo": f"{year}-12-31",
                    "accountNumberFrom": 3000,
                    "accountNumberTo": 8699,
                },
            )
            entries = resp.get("values", [])
            total = sum(e.get("balanceOut", 0) or 0 for e in entries)
            # In Tripletex: revenue = negative balance, expenses = positive
            # Profit = revenue - expenses = -total
            profit = -total
            logger.info(
                "Tax calc: %d entries, total=%s, profit=%s",
                len(entries),
                total,
                profit,
            )
            if profit <= 0:
                # No profit — use absolute value of LLM's amount as-is
                return postings
            real_tax = round(profit * 0.22, 2)
            logger.info("Tax override: profit=%s, tax 22%%=%s", profit, real_tax)
        except Exception:
            return postings

        # Replace amounts in tax postings
        fixed = []
        for p in postings:
            p = dict(p)
            acct = p.get("account") or p.get("debitAccount") or ""
            try:
                acct_num = int(acct)
            except (TypeError, ValueError):
                acct_num = 0
            if 8700 <= acct_num <= 8799:
                # Tax expense — positive (debit)
                for key in ("amount", "debit", "debitAmount", "amountGross"):
                    if key in p:
                        p[key] = real_tax
            elif 2920 <= acct_num <= 2929:
                # Tax payable — negative (credit)
                for key in ("amount", "credit", "creditAmount", "amountGross"):
                    if key in p:
                        p[key] = -real_tax if p[key] < 0 else real_tax
            fixed.append(p)
        return fixed

    @staticmethod
    def _infer_missing_amount(api_client: TripletexClient, posting: dict[str, Any]) -> float:
        """Try to infer a missing amount from existing sandbox data.

        For salary accruals (5000/2900), queries existing salary postings.
        """
        debit_acct = posting.get("debitAccount", "")
        credit_acct = posting.get("creditAccount", "")
        try:
            debit_num = int(debit_acct)
            credit_num = int(credit_acct)
        except (TypeError, ValueError):
            return 0

        # Salary accrual: debit 5000 (salary expense), credit 2900 (accrued)
        # Look at existing salary postings on account 5000
        if 5000 <= debit_num <= 5099 and 2900 <= credit_num <= 2999:
            try:
                from datetime import date as dt_date

                today = dt_date.today()
                resp = api_client.get(
                    "/balanceSheet",
                    params={
                        "dateFrom": f"{today.year}-01-01",
                        "dateTo": today.isoformat(),
                        "accountNumberFrom": str(debit_num),
                        "accountNumberTo": str(debit_num),
                    },
                )
                entries = resp.get("values", [])
                if entries:
                    balance = entries[0].get("balanceOut", 0) or 0
                    if balance > 0:
                        logger.info(
                            "Inferred salary accrual amount %s from account %d",
                            balance,
                            debit_num,
                        )
                        return balance
            except Exception:
                logger.warning("Could not infer salary amount from account %d", debit_num)
        return 0

    @staticmethod
    def _acct_num(posting: dict) -> int:
        acct = (
            posting.get("account")
            or posting.get("debitAccount")
            or posting.get("creditAccount")
            or 0
        )
        try:
            return int(acct)
        except (TypeError, ValueError):
            return 0


@register_handler
class ReverseVoucherHandler(BaseHandler):
    """PUT /ledger/voucher/{id}/:reverse."""

    tier = 3
    description = "Reverse an existing voucher"

    def get_task_type(self) -> str:
        return "reverse_voucher"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        if "voucherId" not in params and params.get("customer"):
            from src.handlers.base import HANDLER_REGISTRY

            pay_params = dict(params)
            amount = params.get("amount", 0)
            pay_params["amount"] = -abs(amount) if amount > 0 else amount
            pay_params["reversal"] = True
            handler = HANDLER_REGISTRY["register_payment"]
            return handler.execute(api_client, pay_params)

        voucher_id = params.get("voucherId")
        if voucher_id:
            voucher_id = int(voucher_id)
            try:
                api_client.get(f"/ledger/voucher/{voucher_id}")
            except TripletexApiError:
                found = self._search_voucher(api_client, params)
                if found:
                    voucher_id = found
                else:
                    return {"error": "voucher_not_found"}
        else:
            voucher_id = self._search_voucher(api_client, params)

        if not voucher_id:
            return {"error": "no_voucher_id"}

        body: dict[str, Any] = {"id": voucher_id}
        date_val = self.validate_date(params.get("date"), "date") or dt_date.today().isoformat()
        body["date"] = date_val

        api_client.put(f"/ledger/voucher/{voucher_id}/:reverse", data=body)
        logger.info("Reversed voucher id=%s", voucher_id)
        return {"id": voucher_id, "action": "reversed"}

    def _search_voucher(self, api_client: TripletexClient, params: dict[str, Any]) -> int | None:
        from datetime import date as dt_date

        today = dt_date.today()
        search: dict[str, Any] = {
            "dateFrom": f"{today.year}-01-01",
            "dateTo": today.isoformat(),
            "count": 10,
        }
        if params.get("voucherNumber"):
            search["number"] = str(params["voucherNumber"])
        elif params.get("voucherId"):
            search["number"] = str(params["voucherId"])
        try:
            resp = api_client.get("/ledger/voucher", params=search, fields="id,number")
            values = resp.get("values", [])
            if values:
                return values[0]["id"]
        except TripletexApiError:
            pass
        return None
