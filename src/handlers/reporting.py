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

        # Build correction postings — from explicit postings or corrections array
        postings = params.get("postings", [])
        corrections = params.get("corrections", [])
        if not postings and corrections:
            postings = self._corrections_to_postings(corrections)
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

    @staticmethod
    def _corrections_to_postings(corrections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert structured corrections into balanced debit/credit postings."""
        postings: list[dict[str, Any]] = []
        for c in corrections:
            ctype = c.get("type", "")
            desc = c.get("description", "Korreksjon")

            # Auto-detect type from fields if not specified
            if not ctype:
                if "wrongAccount" in c and "correctAccount" in c:
                    ctype = "wrong_account"
                elif "recordedAmount" in c and "correctAmount" in c:
                    ctype = "incorrect_amount"
                elif "vatAccount" in c:
                    ctype = "missing_vat"

            if ctype == "wrong_account":
                amt = c.get("amount", 0)
                postings.append({"account": c["correctAccount"], "debit": amt, "description": desc})
                postings.append({"account": c["wrongAccount"], "credit": amt, "description": desc})

            elif ctype in ("duplicate_voucher", "duplicate_reversal", "duplicate"):
                amt = c.get("amount", 0)
                acct = c.get("account", 1920)
                postings.append({"account": 1920, "debit": amt, "description": desc})
                postings.append({"account": acct, "credit": amt, "description": desc})

            elif ctype == "missing_vat":
                net = c.get("netAmount") or c.get("amount") or 0
                vat = round(net * 0.25, 2)
                vat_acct = c.get("vatAccount", 2710)
                exp_acct = c.get("expenseAccount") or c.get("account") or 6500
                postings.append({"account": vat_acct, "debit": vat, "description": desc})
                postings.append({"account": exp_acct, "credit": vat, "description": desc})

            elif ctype == "incorrect_amount":
                diff = c.get("difference")
                if diff is None:
                    recorded = c.get("recordedAmount", 0)
                    correct = c.get("correctAmount", 0)
                    diff = recorded - correct
                acct = c.get("account", 7300)
                if diff > 0:
                    # Overstated — reduce: credit expense, debit bank
                    postings.append({"account": 1920, "debit": abs(diff), "description": desc})
                    postings.append({"account": acct, "credit": abs(diff), "description": desc})
                elif diff < 0:
                    # Understated — increase: debit expense, credit bank
                    postings.append({"account": acct, "debit": abs(diff), "description": desc})
                    postings.append({"account": 1920, "credit": abs(diff), "description": desc})
            else:
                # Generic fallback
                amt = c.get("amount", 0)
                acct = c.get("account", c.get("debitAccount", 7300))
                counter = c.get("counterAccount", c.get("creditAccount", 1920))
                if amt:
                    postings.append({"account": acct, "debit": abs(amt), "description": desc})
                    postings.append({"account": counter, "credit": abs(amt), "description": desc})

        return postings


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
            # Generate closing entries + tax calculation
            closing = self._generate_closing_postings(api_client, year, date)
            tax = self._calculate_tax_posting(api_client, year, date)
            all_postings = closing + tax
            # Re-number rows sequentially (no gaps)
            for i, p in enumerate(all_postings):
                p["row"] = i + 1
            body["postings"] = all_postings

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

        # Fetch all accounts with VAT types for proper closing postings
        all_accts = {}
        try:
            acct_resp = api_client.get(
                "/ledger/account", params={"count": 1000}, fields="id,number,vatType(id)"
            )
            for a in acct_resp.get("values", []):
                all_accts[a["id"]] = a
        except TripletexApiError:
            pass

        for entry in entries:
            balance = entry.get("balanceOut", 0) or 0
            if abs(balance) < 0.01:
                continue
            acct = entry.get("account", {})
            acct_id = acct.get("id")
            if not acct_id:
                continue
            posting: dict[str, Any] = {
                "row": row,
                "account": {"id": acct_id},
                "amountGross": -balance,
                "amountGrossCurrency": -balance,
            }
            # Include VAT type if account has one (required for locked accounts)
            acct_info = all_accts.get(acct_id, {})
            vat = acct_info.get("vatType")
            if vat and vat.get("id"):
                posting["vatType"] = {"id": vat["id"]}
            postings.append(posting)
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

    def _calculate_tax_posting(
        self, api_client: TripletexClient, year: int, date: str
    ) -> list[dict[str, Any]]:
        """Calculate 22% tax on taxable profit and return postings."""
        try:
            # Get revenue (3000-3999) and expenses (4000-8699)
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
            # Sum all balances — negative = revenue, positive = expense
            total_result = sum(e.get("balanceOut", 0) or 0 for e in entries)
            # Profit = negative total (revenue > expenses)
            profit = -total_result
            if profit <= 0:
                return []  # No tax on loss

            tax = round(profit * 0.22, 2)

            from src.services.posting_builder import resolve_account

            acct_8700, vat_8700 = resolve_account(api_client, 8700)
            acct_2920, vat_2920 = resolve_account(api_client, 2920)

            row = 100  # High row — re-numbered later
            p1: dict[str, Any] = {
                "row": row,
                "account": acct_8700,
                "amountGross": tax,
                "amountGrossCurrency": tax,
                "description": f"Skattekostnad {year} (22%)",
            }
            if vat_8700:
                p1["vatType"] = vat_8700
            p2: dict[str, Any] = {
                "row": row + 1,
                "account": acct_2920,
                "amountGross": -tax,
                "amountGrossCurrency": -tax,
                "description": f"Betalbar skatt {year}",
            }
            if vat_2920:
                p2["vatType"] = vat_2920
            return [p1, p2]
        except (TripletexApiError, Exception) as e:
            logger.warning("Tax calculation failed: %s", e)
            return []


@register_handler
class BalanceSheetReportHandler(BaseHandler):
    """Query balance sheet report via GET /balanceSheet.

    Returns balance sheet data for the specified date range.
    """

    tier = 3
    description = "Query balance sheet report"
    disambiguation = (
        "For tasks comparing two periods (e.g. 'increase from Jan to Feb'), "
        "use TWO separate balance_sheet_report tasks — one per month. "
        "Then the system will compare them automatically."
    )
    param_schema = {
        "dateFrom": ParamSpec(type="date"),
        "dateTo": ParamSpec(type="date"),
    }

    def get_task_type(self) -> str:
        return "balance_sheet_report"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        date_from = params["dateFrom"]
        date_to = params["dateTo"]
        fields = "account(id,number,name),balanceIn,balanceChange,balanceOut"

        query: dict[str, Any] = {"dateFrom": date_from, "dateTo": date_to}
        if "accountNumberFrom" in params:
            query["accountNumberFrom"] = params["accountNumberFrom"]
        if "accountNumberTo" in params:
            query["accountNumberTo"] = params["accountNumberTo"]

        result = api_client.get("/balanceSheet", params=query, fields=fields)
        values = result.get("values", []) if result else []

        # If range spans multiple months, also compute per-month comparison
        # This helps the re-classification step identify increases
        from_month = date_from[:7]  # "2026-01"
        to_month = date_to[:7]  # "2026-02"
        if from_month != to_month:
            try:
                # Query each month separately
                mid = f"{to_month}-01"  # First day of second month
                from datetime import date as _date
                from datetime import timedelta

                end_first = (_date.fromisoformat(mid) - timedelta(days=1)).isoformat()
                m1 = api_client.get(
                    "/balanceSheet",
                    params={**query, "dateFrom": date_from, "dateTo": end_first},
                    fields=fields,
                )
                m2 = api_client.get(
                    "/balanceSheet",
                    params={**query, "dateFrom": mid, "dateTo": date_to},
                    fields=fields,
                )
                # Build comparison: find accounts with biggest increase
                m1_by_id = {e["account"]["id"]: e for e in m1.get("values", [])}
                increases = []
                for e2 in m2.get("values", []):
                    aid = e2["account"]["id"]
                    c2 = abs(e2.get("balanceChange", 0) or 0)
                    c1 = abs(m1_by_id.get(aid, {}).get("balanceChange", 0) or 0)
                    if c2 > c1:
                        increases.append(
                            {
                                "account": e2["account"],
                                "month1_change": c1,
                                "month2_change": c2,
                                "increase": c2 - c1,
                            }
                        )
                increases.sort(key=lambda x: x["increase"], reverse=True)
                if increases:
                    values = values  # Keep original entries
                    return {
                        "entries": values,
                        "top_increases": increases[:5],
                        "action": "report_retrieved",
                        "count": len(values),
                    }
            except Exception:
                logger.warning("Multi-month comparison failed")

        logger.info("Retrieved balance sheet with %d entries", len(values))
        return {"entries": values, "action": "report_retrieved", "count": len(values)}
