"""Reporting and correction handlers: ledger corrections, year-end, balance sheet."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.handlers.ledger import _build_posting

logger = logging.getLogger(__name__)


def _resolve_ref(value: Any) -> dict[str, Any]:
    """Convert an int or dict to a Tripletex object reference {id: ...}."""
    if isinstance(value, dict):
        return value
    return {"id": int(value)}


@register_handler
class LedgerCorrectionHandler(BaseHandler):
    """Create a correcting voucher to fix a ledger entry.

    A ledger correction is a voucher that reverses and re-posts
    with corrected values. API: POST /ledger/voucher with correction postings.
    """

    def get_task_type(self) -> str:
        return "ledger_correction"

    @property
    def required_params(self) -> list[str]:
        return ["date"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"date": params["date"]}

        for field in ("description", "number", "tempNumber"):
            if field in params:
                body[field] = params[field]

        if "voucherType" in params:
            body["typeId"] = int(params["voucherType"])

        # Build correction postings
        postings = params.get("postings", [])
        if postings:
            body["postings"] = [_build_posting(p) for p in postings]

        # If correcting a specific voucher, reverse it first
        if "originalVoucherId" in params:
            orig_id = int(params["originalVoucherId"])
            try:
                api_client.put(
                    f"/ledger/voucher/{orig_id}/:reverse",
                    data={"id": orig_id, "date": params["date"]},
                )
                logger.info("Reversed original voucher id=%s", orig_id)
            except Exception:
                logger.warning("Could not reverse voucher %s, proceeding", orig_id)

        result = api_client.post("/ledger/voucher", data=body)
        value = result.get("value", {})
        logger.info("Created correction voucher id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "correction_created"}


@register_handler
class YearEndClosingHandler(BaseHandler):
    """Execute year-end closing via Tripletex API.

    Creates closing vouchers for the specified year.
    API: POST /ledger/voucher with year-end closing entries.
    """

    def get_task_type(self) -> str:
        return "year_end_closing"

    @property
    def required_params(self) -> list[str]:
        return ["year"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        year = int(params["year"])
        date = params.get("date", f"{year}-12-31")

        body: dict[str, Any] = {
            "date": date,
            "description": params.get("description", f"Year-end closing {year}"),
        }

        if "voucherType" in params:
            body["typeId"] = int(params["voucherType"])

        # Build closing postings if provided
        postings = params.get("postings", [])
        if postings:
            body["postings"] = [_build_posting(p) for p in postings]

        result = api_client.post("/ledger/voucher", data=body)
        value = result.get("value", {})
        logger.info("Created year-end closing voucher id=%s for year %d", value.get("id"), year)
        return {"id": value.get("id"), "year": year, "action": "year_end_closed"}


@register_handler
class BalanceSheetReportHandler(BaseHandler):
    """Query balance sheet report via GET /balanceSheet.

    Returns balance sheet data for the specified date range.
    """

    def get_task_type(self) -> str:
        return "balance_sheet_report"

    @property
    def required_params(self) -> list[str]:
        return ["dateFrom", "dateTo"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = {
            "dateFrom": params["dateFrom"],
            "dateTo": params["dateTo"],
        }

        if "accountNumberFrom" in params:
            query["accountNumberFrom"] = params["accountNumberFrom"]
        if "accountNumberTo" in params:
            query["accountNumberTo"] = params["accountNumberTo"]

        result = api_client.get("/balanceSheet", params=query)
        values = result.get("values", []) if result else []
        logger.info("Retrieved balance sheet with %d entries", len(values))
        return {"entries": values, "action": "report_retrieved", "count": len(values)}
