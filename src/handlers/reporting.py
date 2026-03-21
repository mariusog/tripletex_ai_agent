"""Reporting and correction handlers: ledger corrections, year-end, balance sheet."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler
from src.services.posting_builder import build_posting as _build_posting

logger = logging.getLogger(__name__)


@register_handler
class LedgerCorrectionHandler(BaseHandler):
    """Create a correcting voucher to fix a ledger entry.

    A ledger correction is a voucher that reverses and re-posts
    with corrected values. API: POST /ledger/voucher with correction postings.
    """

    tier = 3
    description = "Create a ledger correction voucher"

    def get_task_type(self) -> str:
        return "ledger_correction"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        date_val = self.validate_date(params.get("date"), "date")
        if not date_val:
            date_val = dt_date.today().isoformat()
        body: dict[str, Any] = {"date": date_val}

        body["description"] = params.get("description", "Korreksjon")

        for field in ("number", "tempNumber"):
            if field in params:
                body[field] = params[field]

        if "voucherType" in params:
            body["typeId"] = int(params["voucherType"])

        # Build correction postings
        postings = params.get("postings", [])
        if postings:
            body["postings"] = [
                _build_posting(api_client, p, row=i + 1) for i, p in enumerate(postings)
            ]

        # If correcting a specific voucher, reverse it first
        if "originalVoucherId" in params:
            orig_id = int(params["originalVoucherId"])
            try:
                api_client.put(
                    f"/ledger/voucher/{orig_id}/:reverse",
                    data={"id": orig_id, "date": date_val},
                )
                logger.info("Reversed original voucher id=%s", orig_id)
            except TripletexApiError:
                logger.warning("Could not reverse voucher %s, proceeding", orig_id)

        if not body.get("postings"):
            return {"error": "no_postings", "action": "correction_skipped"}

        result = api_client.post("/ledger/voucher", data=body)
        value = result.get("value", {})
        logger.info("Created correction voucher id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "correction_created"}


@register_handler
class YearEndClosingHandler(BaseHandler):
    """Execute year-end closing via Tripletex API.

    If postings are provided by the LLM, uses those directly.
    Otherwise, reads the result budget and generates closing entries
    that zero out revenue/expense accounts to equity (8800).
    """

    tier = 3
    description = "Execute year-end closing"
    param_schema = {"year": ParamSpec(type="number", description="Fiscal year")}

    def get_task_type(self) -> str:
        return "year_end_closing"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        year = int(params["year"])
        date = params.get("date", f"{year}-12-31")

        body: dict[str, Any] = {
            "date": date,
            "description": params.get("description", f"Årsoppgjør {year}"),
        }

        if "voucherType" in params:
            body["typeId"] = int(params["voucherType"])

        postings = params.get("postings", [])
        if postings:
            body["postings"] = [
                _build_posting(api_client, p, row=i + 1) for i, p in enumerate(postings)
            ]
        else:
            body["postings"] = self._generate_closing_postings(api_client, year, date)

        if not body.get("postings"):
            return {"year": year, "action": "no_postings_needed"}

        result = api_client.post(
            "/ledger/voucher",
            data=body,
            params={"sendToLedger": "true"},
        )
        value = result.get("value", {})
        logger.info(
            "Created year-end closing voucher id=%s for year %d",
            value.get("id"),
            year,
        )
        return {"id": value.get("id"), "year": year, "action": "year_end_closed"}

    def _generate_closing_postings(
        self, api_client: TripletexClient, year: int, date: str
    ) -> list[dict[str, Any]]:
        """Auto-generate closing entries from the balance sheet.

        Revenue/expense accounts (3000-8999) are closed to
        annual result account (8800).
        """
        try:
            resp = api_client.get(
                "/balanceSheet",
                params={
                    "dateFrom": f"{year}-01-01",
                    "dateTo": f"{year}-12-31",
                    "accountNumberFrom": 3000,
                    "accountNumberTo": 8999,
                },
            )
        except TripletexApiError:
            logger.warning("Could not fetch balance sheet for year %d", year)
            return []

        entries = resp.get("values", [])
        postings: list[dict[str, Any]] = []
        total = 0.0
        row = 1

        for entry in entries:
            balance = entry.get("closingBalance", 0) or 0
            if abs(balance) < 0.01:
                continue
            acct = entry.get("account", {})
            acct_id = acct.get("id")
            if not acct_id:
                continue
            postings.append(
                {
                    "row": row,
                    "account": {"id": acct_id},
                    "amountGross": -balance,
                    "amountGrossCurrency": -balance,
                }
            )
            total += balance
            row += 1

        if abs(total) >= 0.01:
            equity_resp = api_client.get(
                "/ledger/account",
                params={"number": "2050", "count": 1},
                fields="id",
            )
            equity_vals = equity_resp.get("values", [])
            if equity_vals:
                postings.append(
                    {
                        "row": row,
                        "account": {"id": equity_vals[0]["id"]},
                        "amountGross": total,
                        "amountGrossCurrency": total,
                    }
                )

        return postings


@register_handler
class BalanceSheetReportHandler(BaseHandler):
    """Query balance sheet report via GET /balanceSheet.

    Returns balance sheet data for the specified date range.
    """

    tier = 3
    description = "Query balance sheet report"
    param_schema = {
        "dateFrom": ParamSpec(type="date"),
        "dateTo": ParamSpec(type="date"),
    }

    def get_task_type(self) -> str:
        return "balance_sheet_report"

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
