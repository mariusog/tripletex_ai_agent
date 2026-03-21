"""Ledger/voucher handlers: create and reverse vouchers via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


def _resolve_supplier(api_client: TripletexClient, supplier: Any) -> dict[str, int] | None:
    """Resolve supplier to {"id": N}. Creates if not found."""
    if supplier is None:
        return None
    if isinstance(supplier, dict) and "id" in supplier:
        return {"id": int(supplier["id"])}
    if isinstance(supplier, (int, float)):
        return {"id": int(supplier)}
    name = str(supplier) if not isinstance(supplier, dict) else supplier.get("name", "")
    org_nr = supplier.get("organizationNumber") if isinstance(supplier, dict) else None
    email = supplier.get("email") if isinstance(supplier, dict) else None
    if not name:
        return None
    # Always create to ensure correct attributes
    sup_body: dict[str, Any] = {"name": name}
    if org_nr:
        sup_body["organizationNumber"] = str(org_nr)
    if email:
        sup_body["email"] = email
        sup_body["invoiceEmail"] = email
    try:
        result = api_client.post("/supplier", data=sup_body)
        sup_id = result.get("value", {}).get("id")
        logger.info("Created supplier '%s' id=%s", name, sup_id)
        return {"id": sup_id}
    except TripletexApiError:
        pass
    # Fallback: search
    try:
        resp = api_client.get("/supplier", params={"name": name, "count": 5}, fields="id,name")
        for v in resp.get("values", []):
            if v.get("name", "").strip().lower() == name.strip().lower():
                return {"id": v["id"]}
    except TripletexApiError:
        pass
    return None


@register_handler
class CreateSupplierHandler(BaseHandler):
    """POST /supplier with extracted fields. 1 API call."""

    def get_task_type(self) -> str:
        return "create_supplier"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

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
                body[addr_field] = params[addr_field]
        body = self.strip_none_values(body)
        result = api_client.post("/supplier", data=body)
        value = result.get("value", {})
        logger.info("Created supplier id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


def _resolve_account(
    api_client: TripletexClient, account: Any
) -> tuple[dict[str, int], dict[str, int] | None]:
    """Resolve account number to ({"id": N}, vatType ref or None)."""
    if isinstance(account, dict) and "id" in account:
        return {"id": int(account["id"])}, None
    try:
        number = int(account)
    except (TypeError, ValueError):
        return {"id": 0}, None
    resp = api_client.get(
        "/ledger/account",
        params={"number": str(number), "count": 1},
        fields="id,vatType(id)",
    )
    values = resp.get("values", [])
    if values:
        vat = values[0].get("vatType")
        vat_ref = {"id": vat["id"]} if vat and vat.get("id") else None
        return {"id": values[0]["id"]}, vat_ref
    logger.warning("Account %d not found", number)
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
    if debit and not credit:
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
    # Set VAT type from account default if not explicitly provided
    if "vatType" in posting:
        result["vatType"] = BaseHandler.ensure_ref(posting["vatType"], "vatType")
    elif vat_ref:
        result["vatType"] = vat_ref
    # Add supplier ref if provided (required for AP/supplier invoice postings)
    if supplier:
        result["supplier"] = supplier
    return {k: v for k, v in result.items() if v is not None}


@register_handler
class CreateVoucherHandler(BaseHandler):
    """POST /ledger/voucher with debit/credit postings. 1 API call."""

    def get_task_type(self) -> str:
        return "create_voucher"

    @property
    def required_params(self) -> list[str]:
        return []

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

        # Normalize postings: split debitAccount/creditAccount into separate rows
        raw_postings = params.get("postings", [])
        postings: list[dict[str, Any]] = []
        for p in raw_postings:
            if "debitAccount" in p and "creditAccount" in p:
                amt = p.get("amount", p.get("amountGross", 0))
                postings.append(
                    {
                        "account": p["debitAccount"],
                        "debit": amt,
                        "description": p.get("description", ""),
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
                postings.append(p)

        if postings:
            body["postings"] = [
                _build_posting(api_client, p, row=i + 1, supplier=supplier_ref)
                for i, p in enumerate(postings)
            ]

        body = self.strip_none_values(body)
        result = api_client.post(
            "/ledger/voucher",
            data=body,
            params={"sendToLedger": "true"},
        )
        value = result.get("value", {})
        logger.info("Created voucher id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class ReverseVoucherHandler(BaseHandler):
    """POST /ledger/voucher/{id}/:reverse. 1 API call."""

    def get_task_type(self) -> str:
        return "reverse_voucher"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        # If no voucherId, fall back to register_payment with reversal
        if "voucherId" not in params and params.get("customer"):
            from src.handlers.invoice import RegisterPaymentHandler

            pay_params = dict(params)
            amount = params.get("amount", 0)
            pay_params["amount"] = -abs(amount) if amount > 0 else amount
            pay_params["reversal"] = True
            handler = RegisterPaymentHandler()
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
