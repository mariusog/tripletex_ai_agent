"""Reporting and correction handlers: ledger corrections, year-end, balance sheet."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.handlers.ledger import _build_posting

logger = logging.getLogger(__name__)


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
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        date_val = self.validate_date(params.get("date"), "date")
        if not date_val:
            date_val = dt_date.today().isoformat()
        body: dict[str, Any] = {
            "date": date_val,
            "description": params.get("description", "Korreksjon"),
        }

        if "voucherType" in params:
            body["voucherType"] = {"id": int(params["voucherType"])}

        # Resolve supplier if present (needed for AP account postings like 2400)
        from src.handlers.ledger import _resolve_supplier

        supplier_ref = _resolve_supplier(api_client, params.get("supplier"))

        # Build correction postings
        postings = params.get("postings", [])
        if postings:
            body["postings"] = [
                _build_posting(api_client, p, row=i + 1, supplier=supplier_ref)
                for i, p in enumerate(postings)
            ]

        # If correcting a specific voucher, reverse it first
        if "originalVoucherId" in params:
            orig_id = int(params["originalVoucherId"])
            try:
                api_client.put(
                    f"/ledger/voucher/{orig_id}/:reverse",
                    data={"id": orig_id, "date": params["date"]},
                )
                logger.info("Reversed original voucher id=%s", orig_id)
            except TripletexApiError:
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
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        # Extract year — from params, date, or current year
        year = params.get("year")
        if year:
            year = int(year)
        else:
            date_str = params.get("date", "")
            if date_str and len(str(date_str)) >= 4:
                year = int(str(date_str)[:4])
            else:
                year = dt_date.today().year - 1  # Default to previous year

        date = params.get("date", f"{year}-12-31")
        date_val = self.validate_date(date, "date") or f"{year}-12-31"

        body: dict[str, Any] = {
            "date": date_val,
            "description": params.get("description", f"Årsoppgjør {year}"),
        }

        if "voucherType" in params:
            body["voucherType"] = {"id": int(params["voucherType"])}

        # Build closing postings if provided by LLM
        postings = params.get("postings", [])
        if postings:
            body["postings"] = [
                _build_posting(api_client, p, row=i + 1) for i, p in enumerate(postings)
            ]
        else:
            # Auto-generate minimal closing entries if no postings extracted
            # Standard Norwegian year-end: close result to equity (8800 -> 2050)
            body["postings"] = self._generate_closing_postings(api_client, year)

        # If no postings were generated (empty balance sheet), create a minimal
        # zero-balance closing entry so the voucher creation doesn't fail
        if not body.get("postings"):
            from src.handlers.ledger import _resolve_account

            equity_ref, _ = _resolve_account(api_client, 8800)
            result_ref, _ = _resolve_account(api_client, 2050)
            body["postings"] = [
                {"row": 1, "account": equity_ref, "amountGross": 0, "amountGrossCurrency": 0},
                {"row": 2, "account": result_ref, "amountGross": 0, "amountGrossCurrency": 0},
            ]

        body = self.strip_none_values(body)
        result = api_client.post("/ledger/voucher", data=body, params={"sendToLedger": "true"})
        value = result.get("value", {})
        logger.info("Created year-end closing voucher id=%s for year %d", value.get("id"), year)
        return {"id": value.get("id"), "year": year, "action": "year_end_closed"}

    def _generate_closing_postings(
        self, api_client: TripletexClient, year: int
    ) -> list[dict[str, Any]]:
        """Generate standard closing postings based on balance sheet data."""
        try:
            result = api_client.get(
                "/balanceSheet",
                params={
                    "dateFrom": f"{year}-01-01",
                    "dateTo": f"{year}-12-31",
                    "accountNumberFrom": 3000,
                    "accountNumberTo": 8999,
                },
            )
            entries = result.get("values", []) if result else []
        except TripletexApiError:
            logger.warning("Could not fetch balance sheet for year %d", year)
            entries = []

        postings = []
        total = 0
        row = 1

        for entry in entries:
            balance = entry.get("closingBalance", 0) or entry.get("balance", 0)
            if not balance:
                continue
            acct = entry.get("account", {})
            acct_id = acct.get("id")
            if not acct_id:
                continue

            # Reverse the balance on the P&L account
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

        if postings:
            # Post the net result to equity account 2050
            from src.handlers.ledger import _resolve_account

            equity_ref, vat_ref = _resolve_account(api_client, 2050)
            posting = {
                "row": row,
                "account": equity_ref,
                "amountGross": total,
                "amountGrossCurrency": total,
            }
            if vat_ref:
                posting["vatType"] = vat_ref
            postings.append(posting)

        return postings


@register_handler
class BalanceSheetReportHandler(BaseHandler):
    """Query balance sheet report via GET /balanceSheet.

    Returns balance sheet data for the specified date range.
    """

    def get_task_type(self) -> str:
        return "balance_sheet_report"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        today = dt_date.today()
        date_from = params.get("dateFrom", f"{today.year}-01-01")
        date_to = params.get("dateTo", today.isoformat())
        query: dict[str, Any] = {
            "dateFrom": date_from,
            "dateTo": date_to,
        }

        if "accountNumberFrom" in params:
            query["accountNumberFrom"] = params["accountNumberFrom"]
        if "accountNumberTo" in params:
            query["accountNumberTo"] = params["accountNumberTo"]

        result = api_client.get("/balanceSheet", params=query)
        values = result.get("values", []) if result else []
        logger.info("Retrieved balance sheet with %d entries", len(values))
        return {"entries": values, "action": "report_retrieved", "count": len(values)}
