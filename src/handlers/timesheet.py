"""Timesheet handler: log hours and optionally invoice via Tripletex API."""

from __future__ import annotations

import contextlib
import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.handlers.entity_resolver import resolve
from src.handlers.resolvers import ensure_bank_account

logger = logging.getLogger(__name__)


def _create_activity(
    api_client: TripletexClient,
    name: str,
    project_ref: dict[str, int] | None = None,
) -> dict[str, int]:
    """Resolve an activity by name and link it to a project if provided."""
    act_ref = resolve(api_client, "activity", name)
    if not act_ref.get("id"):
        return {"id": 0}
    # Link activity to project so it can be used in timesheet entries
    if project_ref and act_ref.get("id"):
        with contextlib.suppress(TripletexApiError):
            api_client.post(
                "/project/projectActivity",
                data={"project": project_ref, "activity": act_ref},
            )
    return act_ref


def _create_project(
    api_client: TripletexClient,
    name: str,
    customer_ref: dict[str, int] | None = None,
    pm_ref: dict[str, int] | None = None,
) -> dict[str, int]:
    """Always create a project by name."""
    import secrets

    body: dict[str, Any] = {
        "name": name,
        "number": str(secrets.randbelow(90000) + 10000),
        "startDate": dt_date.today().isoformat(),
        "projectManager": pm_ref or {"id": 0},
    }
    if customer_ref:
        body["customer"] = customer_ref
    try:
        result = api_client.post("/project", data=body)
        proj_id = result.get("value", {}).get("id")
        logger.info("Created project '%s' id=%s", name, proj_id)
        return {"id": proj_id}
    except TripletexApiError:
        # Search as fallback
        resp = api_client.get("/project", params={"name": name, "count": 5}, fields="id,name")
        for v in resp.get("values", []):
            if (v.get("name") or "").strip().lower() == name.strip().lower():
                return {"id": v["id"]}
    return {"id": 0}


@register_handler
class LogTimesheetHandler(BaseHandler):
    """Log timesheet hours and optionally generate a project invoice."""

    def get_task_type(self) -> str:
        return "log_timesheet"

    @property
    def required_params(self) -> list[str]:
        return ["employee"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today().isoformat()

        # Step 1: Resolve employee
        emp_ref = resolve(api_client, "employee", params["employee"])

        # Step 2: Get PM (account owner) for project creation
        pm_search = api_client.get("/employee", params={"count": 1}, fields="id")
        pm_vals = pm_search.get("values", [])
        pm_ref = {"id": pm_vals[0]["id"]} if pm_vals else emp_ref

        # Step 3: Resolve customer if specified
        customer_ref = None
        if params.get("customer"):
            cust = params["customer"]
            if isinstance(cust, str):
                org = params.get("organizationNumber")
                if org:
                    cust = {"name": cust, "organizationNumber": org}
            customer_ref = resolve(api_client, "customer", cust)

        # Step 4: Find or create project
        project_ref = None
        proj_name = params.get("project")
        if isinstance(proj_name, dict):
            proj_name = proj_name.get("name", "")
        if proj_name:
            project_ref = _create_project(api_client, proj_name, customer_ref, pm_ref)

        # Step 5: Find or create activity
        activity_ref = None
        act_name = params.get("activity")
        if isinstance(act_name, dict):
            act_name = act_name.get("name", "")
        if act_name:
            activity_ref = _create_activity(api_client, act_name, project_ref)

        # Step 6: Create timesheet entry
        hours = params.get("hours") or params.get("hoursLogged") or 0
        entry_body: dict[str, Any] = {
            "employee": emp_ref,
            "date": params.get("date") or today,
            "hours": float(hours),
        }
        if project_ref:
            entry_body["project"] = project_ref
        if activity_ref:
            entry_body["activity"] = activity_ref
        if params.get("comment"):
            entry_body["comment"] = params["comment"]

        try:
            result = api_client.post("/timesheet/entry", data=entry_body)
            entry_id = result.get("value", {}).get("id")
            logger.info("Created timesheet entry id=%s", entry_id)
        except TripletexApiError as e:
            logger.warning("Timesheet entry failed: %s", e)
            entry_id = None

        # Step 7: Generate invoice if requested
        invoice_id = None
        if params.get("generateInvoice") or params.get("hourlyRate"):
            invoice_id = self._create_project_invoice(api_client, params, customer_ref, project_ref)

        return {
            "entryId": entry_id,
            "invoiceId": invoice_id,
            "action": "timesheet_logged",
        }

    def _create_project_invoice(
        self,
        api_client: TripletexClient,
        params: dict[str, Any],
        customer_ref: dict[str, int] | None,
        project_ref: dict[str, int] | None,
    ) -> int | None:
        """Create an invoice from logged project hours."""
        today = dt_date.today().isoformat()
        ensure_bank_account(api_client)

        if not customer_ref:
            return None

        hours = params.get("hours") or params.get("hoursLogged") or 0
        rate = params.get("hourlyRate", 0)
        act_name = params.get("activity")
        if isinstance(act_name, dict):
            act_name = act_name.get("name", "")

        order_body: dict[str, Any] = {
            "customer": customer_ref,
            "orderDate": today,
            "deliveryDate": today,
        }
        if project_ref:
            order_body["project"] = project_ref

        try:
            order_result = api_client.post("/order", data=order_body)
            order_id = order_result.get("value", {}).get("id")

            line: dict[str, Any] = {
                "order": {"id": order_id},
                "description": act_name or "Timeregistrering",
                "count": float(hours),
                "unitPriceExcludingVatCurrency": float(rate),
            }
            api_client.post("/order/orderline/list", data=[line])

            inv_result = api_client.post(
                "/invoice",
                data={
                    "invoiceDate": today,
                    "invoiceDueDate": today,
                    "orders": [{"id": order_id}],
                },
            )
            inv_id = inv_result.get("value", {}).get("id")
            logger.info("Created project invoice id=%s", inv_id)
            return inv_id
        except TripletexApiError as e:
            logger.warning("Project invoice failed: %s", e)
            return None
