"""Cost analysis handler: analyze ledger and create projects for top expense accounts."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CostAnalysisHandler(BaseHandler):
    """Analyze expense accounts and create projects/activities for top changes."""

    tier = 3
    description = "Analyze expense increases and create internal projects"
    disambiguation = (
        "ALWAYS use cost_analysis (not balance_sheet_report) when the task asks to: "
        "analyze costs/expenses between two periods AND create projects/activities. "
        "This handler does EVERYTHING: fetches balance data, finds top increases, "
        "creates internal projects + activities. Do NOT split into multiple tasks. "
        "Keywords in any language: kostnadsanalyse, kostnadsauke, expense analysis, "
        "Kostenanalyse, analyse des coûts, análisis de costos, análise de custos, "
        "biggest increase, mayor incremento, største økning."
    )
    param_schema = {
        "dateFrom": ParamSpec(type="date", description="Start of first period (e.g. 2026-01-01)"),
        "dateTo": ParamSpec(type="date", description="End of second period (e.g. 2026-02-28)"),
        "topN": ParamSpec(
            type="number", required=False, description="Number of top accounts (default 3)"
        ),
    }

    def get_task_type(self) -> str:
        return "cost_analysis"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        date_from = params.get("dateFrom", "2026-01-01")
        date_to = params.get("dateTo", "2026-02-28")
        top_n = params.get("topN", 3)

        # Determine month boundaries
        month1_start = date_from[:8] + "01"
        month1_end = date_from[:8] + "31"  # Tripletex handles overflow
        month2_start = date_to[:8] + "01"
        month2_end = date_to[:8] + "31"

        # Fetch balance sheets for each month (expense accounts 4000-7999)
        acct_range = {"accountNumberFrom": 4000, "accountNumberTo": 7999}
        fields = "account(id,number,name),balanceChange"

        try:
            jan = api_client.get(
                "/balanceSheet",
                params={"dateFrom": month1_start, "dateTo": month1_end, **acct_range},
                fields=fields,
            )
            feb = api_client.get(
                "/balanceSheet",
                params={"dateFrom": month2_start, "dateTo": month2_end, **acct_range},
                fields=fields,
            )
        except TripletexApiError as e:
            logger.warning("Could not fetch balance data: %s", e)
            return {"error": "balance_data_unavailable"}

        # Build Jan balances by account number
        jan_changes: dict[int, float] = {}
        for entry in jan.get("values", []):
            acct_num = entry.get("account", {}).get("number", 0)
            jan_changes[acct_num] = entry.get("balanceChange", 0) or 0

        # Find accounts with biggest INCREASE (Feb change > Jan change)
        increases = []
        for entry in feb.get("values", []):
            acct = entry.get("account", {})
            acct_num = acct.get("number", 0)
            acct_name = acct.get("name", f"Konto {acct_num}")
            feb_change = entry.get("balanceChange", 0) or 0
            jan_change = jan_changes.get(acct_num, 0)
            diff = feb_change - jan_change
            if diff > 0:
                increases.append(
                    {
                        "account_number": acct_num,
                        "account_name": acct_name,
                        "jan": jan_change,
                        "feb": feb_change,
                        "change": diff,
                    }
                )

        increases.sort(key=lambda x: x["change"], reverse=True)
        top = increases[:top_n]

        if not top:
            return {"error": "no_significant_changes", "action": "analysis_complete"}

        logger.info(
            "Top %d expense increases: %s",
            top_n,
            [(c["account_name"], c["change"]) for c in top],
        )

        # Get employee as PM
        emp = api_client.get("/employee", params={"count": 1}, fields="id")
        pm_ref = {"id": emp.get("values", [{}])[0].get("id", 0)}

        # Create internal project + activity for each top account
        created = []
        for change in top:
            proj_name = change["account_name"]
            try:
                proj = api_client.post(
                    "/project",
                    data={
                        "name": proj_name,
                        "number": str(secrets.randbelow(90000) + 10000),
                        "projectManager": pm_ref,
                        "isInternal": True,
                        "startDate": dt_date.today().isoformat(),
                    },
                )
                proj_id = proj.get("value", {}).get("id")

                act = api_client.post("/activity", data={"name": proj_name})
                act_id = act.get("value", {}).get("id")

                # Link activity to project
                if proj_id and act_id:
                    try:
                        api_client.post(
                            "/project/projectActivity",
                            data={
                                "project": {"id": proj_id},
                                "activity": {"id": act_id},
                            },
                        )
                    except TripletexApiError:
                        logger.warning("Could not link activity %s to project %s", act_id, proj_id)

                created.append(
                    {
                        "project_id": proj_id,
                        "activity_id": act_id,
                        "account": change["account_number"],
                        "name": proj_name,
                        "change": change["change"],
                    }
                )
                logger.info(
                    "Created project '%s' id=%s, activity id=%s",
                    proj_name,
                    proj_id,
                    act_id,
                )
            except TripletexApiError as e:
                logger.warning("Failed to create project for %s: %s", proj_name, e)

        return {
            "action": "analysis_complete",
            "top_changes": top,
            "created_projects": len(created),
            "details": created,
        }
