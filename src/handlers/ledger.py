"""Ledger/voucher handlers: create and reverse vouchers via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler
from src.handlers.entity_resolver import _resolve_supplier

logger = logging.getLogger(__name__)


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
        # Also set email as invoiceEmail if not separately provided
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


def _resolve_account(
    api_client: TripletexClient, account: Any
) -> tuple[dict[str, int], dict[str, int] | None]:
    """Resolve account number to ({"id": N}, vatType ref or None).

    If exact number not found, searches by number range to find the closest.
    """
    if isinstance(account, dict) and "id" in account:
        return {"id": int(account["id"])}, None
    try:
        number = int(account)
    except (TypeError, ValueError):
        return {"id": 0}, None
    resp = api_client.get_cached(
        f"account_{number}",
        "/ledger/account",
        params={"number": str(number), "count": 1},
        fields="id,number,vatType(id)",
    )
    values = resp.get("values", [])
    if values:
        vat = values[0].get("vatType")
        vat_ref = {"id": vat["id"]} if vat and vat.get("id") else None
        return {"id": values[0]["id"]}, vat_ref
    # Account not found — search by number range (e.g. 6010 → look in 6000-6099)
    range_start = (number // 100) * 100
    range_end = range_start + 99
    try:
        range_resp = api_client.get(
            "/ledger/account",
            params={
                "numberFrom": str(range_start),
                "numberTo": str(range_end),
                "count": 1,
            },
            fields="id,number,vatType(id)",
        )
        range_vals = range_resp.get("values", [])
        if range_vals:
            vat = range_vals[0].get("vatType")
            vat_ref = {"id": vat["id"]} if vat and vat.get("id") else None
            logger.info(
                "Account %d not found, using %d instead",
                number,
                range_vals[0].get("number", 0),
            )
            return {"id": range_vals[0]["id"]}, vat_ref
    except TripletexApiError:
        pass
    logger.warning("Account %d not found in range %d-%d", number, range_start, range_end)
    return {"id": 0}, None


def _build_posting(
    api_client: TripletexClient,
    posting: dict[str, Any],
    row: int = 0,
    supplier: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a single voucher posting payload."""
    result: dict[str, Any] = {"row": row}
    vat_ref = None
    acct = posting.get("account") or posting.get("debitAccount") or posting.get("creditAccount")
    if acct:
        acct_ref, vat_ref = _resolve_account(api_client, acct)
        result["account"] = acct_ref
    for field in ("amountCurrency", "amount", "description"):
        if field in posting and posting[field] is not None:
            result[field] = posting[field]
    # Handle debit/credit amounts
    debit = posting.get("debit", 0) or 0
    credit = posting.get("credit", 0) or 0
    # If debit/credit are booleans (LLM sent True/False), use amount field
    if isinstance(debit, bool):
        raw_amount = posting.get("amount") or posting.get("amountGross") or 0
        amount = abs(raw_amount) if debit else -abs(raw_amount)
    elif isinstance(credit, bool):
        raw_amount = posting.get("amount") or posting.get("amountGross") or 0
        amount = -abs(raw_amount) if credit else abs(raw_amount)
    elif debit and not credit:
        amount = abs(debit)
    elif credit and not debit:
        amount = -abs(credit)
    elif "amountGross" in posting and posting["amountGross"] is not None:
        amount = posting["amountGross"]
    elif "amount" in posting and posting["amount"] is not None:
        amount = posting["amount"]
    else:
        amount = 0
    result["amountGross"] = amount
    result["amountGrossCurrency"] = amount
    # Set VAT type: use account's default (which respects locked accounts)
    if "vatType" in posting:
        vt_val = posting["vatType"]
        # Handle percentage strings like "25%" — don't override account default
        if isinstance(vt_val, str) and "%" in vt_val:
            if vat_ref:
                result["vatType"] = vat_ref
        else:
            result["vatType"] = BaseHandler.ensure_ref(vt_val, "vatType")
    elif vat_ref:
        result["vatType"] = vat_ref
    # Add supplier ref if provided (required for AP/supplier invoice postings)
    if supplier:
        result["supplier"] = supplier
    return {k: v for k, v in result.items() if v is not None}


@register_handler
class CreateVoucherHandler(BaseHandler):
    """POST /ledger/voucher with debit/credit postings. 1 API call."""

    tier = 3
    description = "Create a voucher with debit/credit postings"
    disambiguation = (
        "For supplier invoices (leverandørfaktura), use this. "
        "Use 2 postings: debit expense account with GROSS amount (inkl MVA) + vatType, "
        "credit 2400 with negative gross amount. Do NOT manually split VAT into separate posting."
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

        if "voucherType" in params:
            body["typeId"] = int(params["voucherType"])

        # Resolve supplier if present (needed for supplier invoice vouchers)
        supplier_ref = _resolve_supplier(api_client, params.get("supplier"))

        # Resolve customer if present (needed for accounts receivable postings)
        customer_ref = None
        if params.get("customer"):
            from src.handlers.entity_resolver import resolve as _resolve_entity

            customer_ref = _resolve_entity(api_client, "customer", params["customer"])

        # Detect and fix manual VAT split pattern:
        # If LLM sent 3 postings (expense + VAT 2710 + AP 2400),
        # merge expense+VAT into one posting with gross amount + vatType
        raw_postings = params.get("postings", [])
        vat_rate = params.get("vatRate") or params.get("vat")
        raw_postings = self._merge_vat_postings(raw_postings, vat_rate)

        # Normalize postings: split debitAccount/creditAccount into separate rows
        postings: list[dict[str, Any]] = []
        for p in raw_postings:
            if "debitAccount" in p and "creditAccount" in p:
                amt = p.get("amount", p.get("amountGross", 0))
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
                if vat_rate and "vatRate" not in p and "vatType" not in p:
                    p["vatRate"] = vat_rate
                postings.append(p)

        if postings:
            built = []
            for i, p in enumerate(postings):
                posting = _build_posting(api_client, p, row=i + 1, supplier=supplier_ref)
                # Add customer to accounts receivable postings (1500-1599)
                acct = p.get("account") or p.get("debitAccount") or p.get("creditAccount")
                try:
                    acct_num = int(acct) if acct else 0
                except (TypeError, ValueError):
                    acct_num = 0
                if customer_ref and 1500 <= acct_num <= 1599:
                    posting["customer"] = customer_ref
                built.append(posting)
            body["postings"] = built

        body = self.strip_none_values(body)
        result = api_client.post(
            "/ledger/voucher",
            data=body,
            params={"sendToLedger": "true"},
        )
        value = result.get("value", {})
        logger.info("Created voucher id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}

    @staticmethod
    def _merge_vat_postings(
        postings: list[dict[str, Any]], vat_rate: Any = None
    ) -> list[dict[str, Any]]:
        """Merge manual VAT split into gross posting with vatType.

        If LLM sent: debit 6340 (net), debit 2710 (VAT), credit 2400 (gross)
        Merge to: debit 6340 (gross, with vatRate), credit 2400 (gross)
        Tripletex handles the VAT split automatically when vatType is set.
        """
        if len(postings) < 3:
            return postings

        # Find VAT posting (account 2710-2719 = input VAT accounts)
        vat_idx = None
        for i, p in enumerate(postings):
            acct = p.get("account") or p.get("debitAccount") or ""
            try:
                acct_num = int(acct)
            except (TypeError, ValueError):
                continue
            if 2710 <= acct_num <= 2719:
                vat_idx = i
                break

        if vat_idx is None:
            return postings

        vat_posting = postings[vat_idx]
        vat_amount = (
            vat_posting.get("debit")
            or vat_posting.get("debitAmount")
            or vat_posting.get("amount")
            or 0
        )

        # Find the expense posting (the other debit that isn't VAT or AP)
        expense_idx = None
        for i, p in enumerate(postings):
            if i == vat_idx:
                continue
            acct = p.get("account") or p.get("debitAccount") or ""
            try:
                acct_num = int(acct)
            except (TypeError, ValueError):
                continue
            # Not AP (2400) and not VAT (2710) = expense account
            if acct_num not in range(2400, 2500) and acct_num not in range(2710, 2720):
                debit = p.get("debit") or p.get("debitAmount") or p.get("amount", 0)
                if debit and debit > 0:
                    expense_idx = i
                    break

        if expense_idx is None:
            return postings

        # Merge: expense gets gross amount (net + VAT), VAT posting removed
        merged = list(postings)
        expense = dict(merged[expense_idx])
        net = expense.get("debit") or expense.get("debitAmount") or expense.get("amount") or 0
        gross = net + vat_amount
        expense["debit"] = gross
        expense["debitAmount"] = gross
        if "amount" in expense:
            expense["amount"] = gross
        expense["vatRate"] = vat_rate or 25
        merged[expense_idx] = expense

        # Remove VAT posting
        merged.pop(vat_idx)
        logger.info(
            "Merged VAT posting: net=%s + vat=%s = gross=%s",
            net,
            vat_amount,
            gross,
        )
        return merged


@register_handler
class ReverseVoucherHandler(BaseHandler):
    """POST /ledger/voucher/{id}/:reverse. 1 API call."""

    tier = 3
    description = "Reverse an existing voucher"

    def get_task_type(self) -> str:
        return "reverse_voucher"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        # If no voucherId, fall back to register_payment with reversal
        if "voucherId" not in params and params.get("customer"):
            from src.handlers.base import HANDLER_REGISTRY

            pay_params = dict(params)
            amount = params.get("amount", 0)
            pay_params["amount"] = -abs(amount) if amount > 0 else amount
            pay_params["reversal"] = True
            handler = HANDLER_REGISTRY["register_payment"]
            return handler.execute(api_client, pay_params)

        voucher_id = params.get("voucherId")

        # Search for voucher by number if ID seems like a voucher number
        if voucher_id:
            voucher_id = int(voucher_id)
            # Verify the voucher exists; if not, search by number
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
        """Search for a voucher by number or description."""
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
