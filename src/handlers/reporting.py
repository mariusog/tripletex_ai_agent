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
        from src.handlers.ledger import _resolve_account

        date_val = self.validate_date(params.get("date"), "date")
        if not date_val:
            date_val = dt_date.today().isoformat()

        # Flatten corrections list into postings
        # LLM sends: corrections: [{postings: [...], description: "..."}, ...]
        corrections = params.get("corrections", [])
        flat_postings = params.get("postings", [])
        descriptions = []

        if corrections and not flat_postings:
            for corr in corrections:
                if corr.get("description"):
                    descriptions.append(corr["description"])
                corr_postings = corr.get("postings", [])
                for p in corr_postings:
                    posting = dict(p)
                    if "debitAmount" in posting:
                        posting["debit"] = posting.pop("debitAmount", 0)
                    if "creditAmount" in posting:
                        posting["credit"] = posting.pop("creditAmount", 0)
                    flat_postings.append(posting)

        description = (
            params.get("description")
            or "; ".join(descriptions[:3])
            or "Korreksjon"
        )

        body: dict[str, Any] = {
            "date": date_val,
            "description": description,
        }

        for field in ("number", "tempNumber"):
            if field in params:
                body[field] = params[field]

        if "voucherType" in params:
            body["typeId"] = int(params["voucherType"])

        # Build correction postings
        if flat_postings:
            built = [
                _build_posting(api_client, p, row=i + 1)
                for i, p in enumerate(flat_postings)
            ]

            # Auto-balance: if postings don't sum to zero, add balancing entry
            total = sum(p.get("amountGross", 0) for p in built)
            if total != 0:
                contra_acct = 1920 if total > 0 else 2400
                contra_ref, _ = _resolve_account(api_client, contra_acct)
                built.append({
                    "row": len(built) + 1,
                    "account": contra_ref,
                    "amountGross": -total,
                    "amountGrossCurrency": -total,
                    "description": "Balansering",
                })
                logger.info("Auto-balanced correction: %s on account %s", -total, contra_acct)

            body["postings"] = built

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

        body = self.strip_none_values(body)
        result = api_client.post(
            "/ledger/voucher", data=body, params={"sendToLedger": "true"},
        )
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
