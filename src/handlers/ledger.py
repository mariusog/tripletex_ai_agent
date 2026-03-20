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
    if not name:
        return None
    # Search by name (verify exact match — API search is fuzzy)
    try:
        resp = api_client.get("/supplier", params={"name": name, "count": 5}, fields="id,name")
        values = resp.get("values", [])
        logger.info("Supplier search for '%s' returned %d results", name, len(values))
        for v in values:
            if v.get("name", "").strip().lower() == name.strip().lower():
                logger.info("Found exact supplier match: id=%s name='%s'", v["id"], v.get("name"))
                return {"id": v["id"]}
    except TripletexApiError:
        pass  # Search failed, create instead
    # Create
    sup_body: dict[str, Any] = {"name": name}
    if org_nr:
        sup_body["organizationNumber"] = str(org_nr)
    result = api_client.post("/supplier", data=sup_body)
    sup_id = result.get("value", {}).get("id")
    logger.info("Auto-created supplier '%s' id=%s", name, sup_id)
    return {"id": sup_id}


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
    if "account" in posting:
        acct_ref, vat_ref = _resolve_account(api_client, posting["account"])
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

        if params.get("description"):
            body["description"] = params["description"]
        # number and tempNumber are readOnly (system-generated)

        if "voucherType" in params:
            body["voucherType"] = {"id": int(params["voucherType"])}

        # Resolve supplier if present (needed for supplier invoice vouchers)
        supplier_ref = _resolve_supplier(api_client, params.get("supplier"))

        # Build postings — resolve account numbers to IDs
        postings = params.get("postings", [])
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
class DeleteVoucherHandler(BaseHandler):
    """GET /ledger/voucher (search) then DELETE /ledger/voucher/{id}."""

    def get_task_type(self) -> str:
        return "delete_voucher"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        voucher_id = params.get("voucherId") or params.get("id")
        if not voucher_id:
            # Search for voucher
            search_params: dict[str, Any] = {"count": 10}
            if params.get("date"):
                date_val = self.validate_date(params["date"], "date")
                if date_val:
                    search_params["dateFrom"] = date_val
                    search_params["dateTo"] = date_val
            if params.get("number"):
                search_params["number"] = str(params["number"])
            resp = api_client.get(
                "/ledger/voucher", params=search_params, fields="id,number,description"
            )
            values = resp.get("values", [])
            if not values:
                logger.warning("No vouchers found to delete")
                return {"error": "not_found"}
            # Match by description if given
            desc = params.get("description", "")
            if desc:
                for v in values:
                    if desc.lower() in (v.get("description") or "").lower():
                        voucher_id = v["id"]
                        break
            if not voucher_id:
                voucher_id = values[0]["id"]

        api_client.delete(f"/ledger/voucher/{int(voucher_id)}")
        logger.info("Deleted voucher id=%s", voucher_id)
        return {"id": int(voucher_id), "action": "deleted"}


@register_handler
class ReverseVoucherHandler(BaseHandler):
    """POST /ledger/voucher/{id}/:reverse. 1 API call."""

    def get_task_type(self) -> str:
        return "reverse_voucher"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        # If no voucherId, fall back to register_payment with reversal
        if "voucherId" not in params and params.get("customer"):
            from src.handlers.invoice import RegisterPaymentHandler

            pay_params = dict(params)
            amount = params.get("amount", 0)
            pay_params["amount"] = -abs(amount) if amount > 0 else amount
            pay_params["reversal"] = True
            handler = RegisterPaymentHandler()
            return handler.execute(api_client, pay_params)

        from datetime import date as dt_date

        voucher_id = int(params.get("voucherId", 0))
        if not voucher_id:
            return {"error": "no_voucher_id"}
        # Spec: PUT /ledger/voucher/{id}/:reverse with date as required query param
        date_val = self.validate_date(params.get("date"), "date") or dt_date.today().isoformat()
        api_client.put(
            f"/ledger/voucher/{voucher_id}/:reverse",
            params={"date": date_val},
        )
        logger.info("Reversed voucher id=%s", voucher_id)
        return {"id": voucher_id, "action": "reversed"}
