"""Cost analysis handler: analyze ledger and create projects for top expense accounts."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CostAnalysisHandler(BaseHandler):
    """Analyze expense accounts and create projects/activities for top changes."""

    def get_task_type(self) -> str:
        return "cost_analysis"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        # Get date ranges
        date_from = params.get("dateFrom", "2026-01-01")
        date_to = params.get("dateTo", "2026-02-28")
        top_n = params.get("topN", 3)

        # Step 1: Get balance sheet for expense accounts (6000-7999)
        try:
            jan = api_client.get("/resultBudget", params={
                "dateFrom": date_from[:8] + "01",
                "dateTo": date_from[:8] + "31",
                "accountNumberFrom": 4000, "accountNumberTo": 8999,
            })
            feb = api_client.get("/resultBudget", params={
                "dateFrom": date_to[:8] + "01",
                "dateTo": date_to[:8] + "28",
                "accountNumberFrom": 4000, "accountNumberTo": 8999,
            })
        except TripletexApiError:
            # Fallback to balanceSheet
            try:
                jan = api_client.get("/balanceSheet", params={
                    "dateFrom": date_from[:8] + "01", "dateTo": date_from[:8] + "31",
                    "accountNumberFrom": 4000, "accountNumberTo": 8999,
                })
                feb = api_client.get("/balanceSheet", params={
                    "dateFrom": date_to[:8] + "01", "dateTo": date_to[:8] + "28",
                    "accountNumberFrom": 4000, "accountNumberTo": 8999,
                })
            except TripletexApiError as e:
                logger.warning("Could not fetch balance data: %s", e)
                return {"error": "balance_data_unavailable"}

        # Step 2: Calculate differences
        jan_balances = {}
        for entry in jan.get("values", []):
            acct = entry.get("account", {})
            acct_num = acct.get("number", 0)
            acct_name = acct.get("name", f"Konto {acct_num}")
            balance = entry.get("closingBalance", 0) or 0
            jan_balances[acct_num] = {"name": acct_name, "balance": balance}

        changes = []
        for entry in feb.get("values", []):
            acct = entry.get("account", {})
            acct_num = acct.get("number", 0)
            acct_name = acct.get("name", f"Konto {acct_num}")
            feb_balance = entry.get("closingBalance", 0) or 0
            jan_balance = jan_balances.get(acct_num, {}).get("balance", 0)
            diff = abs(feb_balance - jan_balance)
            if diff > 0:
                changes.append({
                    "account_number": acct_num,
                    "account_name": acct_name,
                    "jan": jan_balance,
                    "feb": feb_balance,
                    "change": diff,
                })

        # Sort by largest change
        changes.sort(key=lambda x: x["change"], reverse=True)
        top = changes[:top_n]

        if not top:
            return {"error": "no_significant_changes", "action": "analysis_complete"}

        logger.info("Top %d expense changes: %s", top_n,
                     [(c["account_name"], c["change"]) for c in top])

        # Step 3: Create project + activity for each top account
        import secrets

        # Get account owner as PM
        emp = api_client.get("/employee", params={"count": 1}, fields="id")
        pm_ref = {"id": emp.get("values", [{}])[0].get("id", 0)}

        created = []
        for change in top:
            proj_name = change["account_name"]
            try:
                proj = api_client.post("/project", data={
                    "name": proj_name,
                    "number": str(secrets.randbelow(90000) + 10000),
                    "projectManager": pm_ref,
                    "startDate": dt_date.today().isoformat(),
                })
                proj_id = proj.get("value", {}).get("id")

                # Create activity for the project
                act = api_client.post("/activity", data={"name": proj_name})
                act_id = act.get("value", {}).get("id")

                created.append({
                    "project_id": proj_id,
                    "activity_id": act_id,
                    "account": change["account_number"],
                    "name": proj_name,
                    "change": change["change"],
                })
                logger.info("Created project '%s' id=%s, activity id=%s",
                           proj_name, proj_id, act_id)
            except TripletexApiError as e:
                logger.warning("Failed to create project for %s: %s", proj_name, e)

        return {
            "action": "analysis_complete",
            "top_changes": top,
            "created_projects": len(created),
            "details": created,
        }
