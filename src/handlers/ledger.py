"""Ledger/voucher handlers: create and reverse vouchers via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


def _resolve_account(
    api_client: TripletexClient, account: Any
) -> dict[str, int]:
    """Resolve account number to {"id": N}."""
    if isinstance(account, dict) and "id" in account:
        return {"id": int(account["id"])}
    try:
        number = int(account)
    except (TypeError, ValueError):
        return {"id": 0}
    resp = api_client.get(
        "/ledger/account",
        params={"number": str(number), "count": 1},
        fields="id",
    )
    values = resp.get("values", [])
    if values:
        return {"id": values[0]["id"]}
    logger.warning("Account %d not found", number)
    return {"id": 0}


def _build_posting(
    api_client: TripletexClient, posting: dict[str, Any]
) -> dict[str, Any]:
    """Build a single voucher posting payload."""
    result: dict[str, Any] = {}
    if "account" in posting:
        result["account"] = _resolve_account(api_client, posting["account"])
    for field in ("amountCurrency", "amount", "description"):
        if field in posting and posting[field] is not None:
            result[field] = posting[field]
    # Handle debit/credit amounts
    debit = posting.get("debit", 0) or 0
    credit = posting.get("credit", 0) or 0
    if debit and not credit:
        result["amountGross"] = abs(debit)
    elif credit and not debit:
        result["amountGross"] = -abs(credit)
    elif "amountGross" in posting and posting["amountGross"] is not None:
        result["amountGross"] = posting["amountGross"]
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

        # Build postings — resolve account numbers to IDs
        postings = params.get("postings", [])
        if postings:
            body["postings"] = [_build_posting(api_client, p) for p in postings]

        body = self.strip_none_values(body)
        result = api_client.post("/ledger/voucher", data=body)
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
        return ["voucherId"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        voucher_id = int(params["voucherId"])
        body: dict[str, Any] = {"id": voucher_id}
        if "date" in params:
            date_val = self.validate_date(params["date"], "date")
            if date_val:
                body["date"] = date_val

        api_client.put(f"/ledger/voucher/{voucher_id}/:reverse", data=body)
        logger.info("Reversed voucher id=%s", voucher_id)
        return {"id": voucher_id, "action": "reversed"}
