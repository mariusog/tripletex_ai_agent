"""Timesheet handler: log hours on project activities via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.handlers.travel import _resolve_employee

logger = logging.getLogger(__name__)


@register_handler
class LogTimesheetHandler(BaseHandler):
    """Log timesheet hours for an employee on a project activity.

    Flow: resolve employee -> resolve project -> resolve activity ->
    POST /timesheet/entry -> optionally create project invoice.
    """

    def get_task_type(self) -> str:
        return "log_timesheet"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today().isoformat()

        # Step 1: Resolve employee
        employee_ref = {"id": 0}
        if params.get("employee"):
            employee_ref = _resolve_employee(api_client, params["employee"])

        # Step 2: Resolve project (search or create)
        project_ref = None
        if params.get("project"):
            proj = params["project"]
            proj_name = proj if isinstance(proj, str) else proj.get("name", "")
            if proj_name:
                search = api_client.get(
                    "/project", params={"name": proj_name, "count": 1}, fields="id"
                )
                values = search.get("values", [])
                if values:
                    project_ref = {"id": values[0]["id"]}
                else:
                    # Create the project
                    from src.handlers.project import CreateProjectHandler

                    proj_params = {"name": proj_name}
                    if params.get("customer"):
                        proj_params["customer"] = params["customer"]
                    result = CreateProjectHandler().execute(api_client, proj_params)
                    if result.get("id"):
                        project_ref = {"id": result["id"]}

        # Step 3: Resolve activity (search or create)
        activity_ref = None
        if params.get("activity"):
            act = params["activity"]
            act_name = act if isinstance(act, str) else act.get("name", "")
            if act_name:
                search = api_client.get(
                    "/activity", params={"name": act_name, "count": 1}, fields="id"
                )
                values = search.get("values", [])
                if values:
                    activity_ref = {"id": values[0]["id"]}
                else:
                    # Create activity
                    try:
                        result = api_client.post("/activity", data={"name": act_name})
                        act_id = result.get("value", {}).get("id")
                        if act_id:
                            activity_ref = {"id": act_id}
                    except TripletexApiError:
                        logger.warning("Could not create activity '%s'", act_name)

        # Step 4: Create timesheet entry
        hours = params.get("hours", 0)
        entry_body: dict[str, Any] = {
            "employee": employee_ref,
            "date": params.get("date", today),
            "hours": hours,
        }
        if project_ref:
            entry_body["project"] = project_ref
        if activity_ref:
            entry_body["activity"] = activity_ref
        if params.get("comment"):
            entry_body["comment"] = params["comment"]

        entry_body = self.strip_none_values(entry_body)
        try:
            result = api_client.post("/timesheet/entry", data=entry_body)
            entry_id = result.get("value", {}).get("id")
            logger.info("Created timesheet entry id=%s, %s hours", entry_id, hours)
        except TripletexApiError as e:
            logger.warning("Timesheet entry failed: %s", e)
            entry_id = None

        # Step 5: Create project invoice if requested
        inv_id = None
        hourly_rate = params.get("hourlyRate", 0)
        if params.get("createInvoice") and project_ref and hourly_rate and hours:
            total = float(hours) * float(hourly_rate)
            from src.handlers.invoice import CreateInvoiceHandler

            inv_params: dict[str, Any] = {
                "customer": params.get("customer"),
                "project": project_ref,
                "orderLines": [
                    {
                        "description": params.get("activity", "Timesheet"),
                        "unitPriceExcludingVatCurrency": total,
                        "count": 1,
                    }
                ],
            }
            try:
                inv_result = CreateInvoiceHandler().execute(api_client, inv_params)
                inv_id = inv_result.get("id")
                logger.info("Created project invoice id=%s", inv_id)
            except Exception as e:
                logger.warning("Project invoice failed: %s", e)

        return {
            "id": entry_id,
            "invoiceId": inv_id,
            "hours": hours,
            "action": "logged",
        }
