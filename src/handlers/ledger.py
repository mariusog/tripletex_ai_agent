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
    disambiguation = (
        "For supplier invoices (leverandørfaktura), use this. "
        "Use 2 postings: debit expense account with GROSS amount (inkl MVA) + vatType, "
        "credit 2400 with negative gross amount. Do NOT manually split VAT."
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

        supplier_ref = _resolve_supplier(api_client, params.get("supplier"))

        customer_ref = None
        if params.get("customer"):
            from src.handlers.entity_resolver import resolve as _resolve_entity

            customer_ref = _resolve_entity(api_client, "customer", params["customer"])

        # If postings use account 1500 (receivable) but no customer, find one
        if not customer_ref:
            needs_customer = any(
                1500 <= self._acct_num(p) <= 1599 for p in params.get("postings", [])
            )
            if needs_customer:
                try:
                    resp = api_client.get("/customer", params={"count": 1}, fields="id")
                    vals = resp.get("values", [])
                    if vals:
                        customer_ref = {"id": vals[0]["id"]}
                except Exception:
                    logger.warning("Could not find customer for receivable posting")

        # Merge manual VAT split if present
        raw_postings = params.get("postings", [])
        vat_rate = params.get("vatRate") or params.get("vat")
        raw_postings = merge_vat_postings(raw_postings, vat_rate)

        # Normalize debitAccount/creditAccount into separate rows
        postings: list[dict[str, Any]] = []
        for p in raw_postings:
            if "debitAccount" in p and "creditAccount" in p:
                amt = p.get("amount", p.get("amountGross", 0))
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
                if vat_rate and "vatRate" not in p and "vatType" not in p:
                    p["vatRate"] = vat_rate
                postings.append(p)

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
                built.append(posting)
            body["postings"] = built

        body = self.strip_none_values(body)
        result = api_client.post("/ledger/voucher", data=body, params={"sendToLedger": "true"})
        value = result.get("value", {})
        logger.info("Created voucher id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}

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
