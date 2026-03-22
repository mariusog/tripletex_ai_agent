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
    param_schema = {
        "corrections": ParamSpec(
            type="list",
            description="Array of corrections: {type, amount, account, description}. "
            "Types: wrong_account ({wrongAccount, correctAccount, amount}), "
            "duplicate_entry ({account, amount}), "
            "missing_vat ({account, amount/netAmount, vatAccount: 2710}), "
            "incorrect_amount ({account, recordedAmount, correctAmount})",
        ),
        "date": ParamSpec(required=False, type="date"),
    }

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
            # Try structured conversion first
            postings = self._corrections_to_postings(corrections)
            # Fallback: extract nested postings from corrections[].postings[]
            if not postings:
                for c in corrections:
                    nested = c.get("postings", [])
                    for p in nested:
                        postings.append(p)
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

        body = self.strip_none_values(body)
        result = api_client.post("/ledger/voucher", data=body, params={"sendToLedger": "true"})
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
                correct = c.get("correctAccount") or c.get("correct_account")
                wrong = c.get("wrongAccount") or c.get("wrong_account") or c.get("account")
                postings.append({"account": correct, "debit": amt, "description": desc})
                postings.append({"account": wrong, "credit": amt, "description": desc})

            elif ctype in (
                "duplicate_voucher",
                "duplicate_reversal",
                "duplicate",
                "duplicate_entry",
            ):
                amt = c.get("amount", 0)
                acct = c.get("account", 1920)
                postings.append({"account": 1920, "debit": amt, "description": desc})
                postings.append({"account": acct, "credit": amt, "description": desc})

            elif ctype in ("missing_vat", "missing_vat_line"):
                net = c.get("netAmount") or c.get("amount") or 0
                vat = round(net * 0.25, 2)
                vat_acct = c.get("vatAccount", 2710)
                # Missing VAT = claim input VAT, reduce supplier debt
                postings.append({"account": vat_acct, "debit": vat, "description": desc})
                postings.append({"account": 2400, "credit": vat, "description": desc})

            elif ctype == "incorrect_amount":
                diff = c.get("difference")
                if diff is None:
                    recorded = c.get("recordedAmount") or c.get("amount") or 0
                    correct = c.get("correctAmount") or 0
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
                # Generic fallback: handle debitAccount/creditAccount format
                debit_acct = c.get("debitAccount") or c.get("debit_account")
                credit_acct = c.get("creditAccount") or c.get("credit_account")
                amt = c.get("amount", 0)
                if debit_acct and credit_acct and amt:
                    postings.append({"account": debit_acct, "debit": abs(amt), "description": desc})
                    postings.append(
                        {"account": credit_acct, "credit": abs(amt), "description": desc}
                    )
                elif amt:
                    acct = c.get("account", 7300)
                    counter = c.get("counterAccount", 1920)
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
    param_schema = {
        "year": ParamSpec(type="number", description="Fiscal year"),
        "depreciation": ParamSpec(
            required=False,
            type="list",
            description="Array of assets: {assetName, cost, years, assetAccount (e.g. 1200), "
            "expenseAccount (e.g. 6010), accumulatedAccount (e.g. 1209)}",
        ),
        "prepaidReversal": ParamSpec(
            required=False,
            type="object",
            description="Prepaid expense reversal: {account (e.g. 1700), amount}",
        ),
        "taxRate": ParamSpec(
            required=False,
            type="number",
            description="Tax rate (default 0.22)",
        ),
        "taxExpenseAccount": ParamSpec(
            required=False,
            type="number",
            description="Tax expense account (default 8700)",
        ),
        "taxLiabilityAccount": ParamSpec(
            required=False,
            type="number",
            description="Tax liability account (default 2920)",
        ),
    }

    def get_task_type(self) -> str:
        return "year_end_closing"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        year = int(params["year"])
        date = params.get("date", f"{year}-12-31")
        created_ids = []

        # Step 1: Depreciation vouchers (one per asset for correctness)
        for dep in params.get("depreciation", []):
            cost = dep.get("cost", 0)
            years = dep.get("years", 1)
            if not cost or not years:
                continue
            annual = round(cost / years, 2)
            exp_acct = dep.get("expenseAccount", 6010)
            acc_acct = dep.get("accumulatedAccount", 1209)
            postings = [
                {"account": exp_acct, "debit": annual,
                 "description": f"Avskriving {dep.get('assetName', '')}"},
                {"account": acc_acct, "credit": annual,
                 "description": f"Akk. avskriving {dep.get('assetName', '')}"},
            ]
            vid = self._post_voucher(api_client, date,
                f"Avskriving {dep.get('assetName', '')} {year}", postings)
            if vid:
                created_ids.append(vid)

        # Step 2: Prepaid expense reversal
        prepaid = params.get("prepaidReversal")
        if prepaid:
            amount = prepaid.get("amount", 0)
            acct = prepaid.get("account", 1700)
            if amount:
                postings = [
                    {"account": 6300, "debit": amount, "description": "Forskuddsbetalt kostnad"},
                    {"account": acct, "credit": amount, "description": "Reversering forskudd"},
                ]
                vid = self._post_voucher(api_client, date,
                    f"Reversering forskuddsbetalt kostnad {year}", postings)
                if vid:
                    created_ids.append(vid)

        # Step 3: Tax provision (22% of taxable profit)
        tax_rate = params.get("taxRate", 0.22)
        tax_exp = params.get("taxExpenseAccount", 8700)
        tax_liab = params.get("taxLiabilityAccount", 2920)
        tax_amount = params.get("taxAmount", 0)
        # If no amount, try to compute from balance sheet
        if not tax_amount and tax_rate:
            tax_amount = self._compute_tax(api_client, year, tax_rate)
        if tax_amount:
            postings = [
                {"account": tax_exp, "debit": tax_amount, "description": f"Skattekostnad {year}"},
                {"account": tax_liab, "credit": tax_amount, "description": f"Betalbar skatt {year}"},
            ]
            vid = self._post_voucher(api_client, date, f"Skattekostnad {year}", postings)
            if vid:
                created_ids.append(vid)

        # Step 4: If LLM sent raw postings, use those
        if not created_ids and params.get("postings"):
            postings = params["postings"]
            vid = self._post_voucher(api_client, date,
                params.get("description", f"Årsoppgjør {year}"), postings)
            if vid:
                created_ids.append(vid)

        # Step 5: Auto-generate closing entries if nothing else worked
        if not created_ids:
            closing = self._generate_closing_postings(api_client, year, date)
            tax_p = self._calculate_tax_posting(api_client, year, date)
            all_p = closing + tax_p
            if all_p:
                for i, p in enumerate(all_p):
                    p["row"] = i + 1
                body = {"date": date, "description": f"Årsoppgjør {year}", "postings": all_p}
                try:
                    result = api_client.post("/ledger/voucher", data=body, params={"sendToLedger": "true"})
                    created_ids.append(result.get("value", {}).get("id"))
                except TripletexApiError as e:
                    logger.warning("Auto closing failed: %s", e)

        if not created_ids:
            return {"year": year, "action": "no_postings_needed"}

        value = {"id": created_ids[0]}
        logger.info(
            "Created year-end closing voucher id=%s for year %d",
            value.get("id"),
            year,
        )
        return {"id": value.get("id"), "year": year, "action": "year_end_closed"}

    def _post_voucher(
        self, api_client: TripletexClient, date: str,
        description: str, postings: list[dict[str, Any]],
    ) -> int | None:
        """Post a single voucher with balanced postings."""
        built = [_build_posting(api_client, p, row=i + 1) for i, p in enumerate(postings)]
        body = {"date": date, "description": description, "postings": built}
        try:
            result = api_client.post("/ledger/voucher", data=body, params={"sendToLedger": "true"})
            vid = result.get("value", {}).get("id")
            logger.info("Created voucher '%s' id=%s", description[:40], vid)
            return vid
        except TripletexApiError as e:
            logger.warning("Voucher '%s' failed: %s", description[:40], e)
            return None

    @staticmethod
    def _compute_tax(api_client: TripletexClient, year: int, rate: float) -> float:
        """Compute tax from P&L balance."""
        try:
            resp = api_client.get("/balanceSheet", params={
                "dateFrom": f"{year}-01-01", "dateTo": f"{year}-12-31",
                "accountNumberFrom": 3000, "accountNumberTo": 8699,
            })
            total = sum(
                entry.get("closingBalance", 0) or 0
                for entry in resp.get("values", [])
            )
            if total < 0:  # Profit is negative in Norwegian accounting
                return round(abs(total) * rate, 2)
        except TripletexApiError:
            pass
        return 0

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
                    "accountNumberTo": 8699,
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
                params={"number": "8800", "count": 1},
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
