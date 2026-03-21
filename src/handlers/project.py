"""Project handlers: create projects, link customers, and create activities."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.handlers.invoice import _resolve_customer
from src.handlers.travel import _resolve_employee

logger = logging.getLogger(__name__)


@register_handler
class CreateProjectHandler(BaseHandler):
    """POST /project with extracted fields. 1 API call."""

    def get_task_type(self) -> str:
        return "create_project"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        # Resolve project manager — try using the requested PM first,
        # fall back to account owner if creation fails
        pm = params.get("projectManager")
        pm_ref = None
        if pm and isinstance(pm, dict) and "id" not in pm:
            emp_ref = _resolve_employee(api_client, pm)
            if emp_ref and emp_ref.get("id"):
                pm_ref = emp_ref
        if not pm_ref:
            emp_search = api_client.get_cached(
                "account_owner", "/employee", params={"count": 1}, fields="id"
            )
            emp_values = emp_search.get("values", [])
            pm_ref = {"id": emp_values[0]["id"]} if emp_values else {"id": 0}

        proj_num = str(params.get("number", abs(hash(params["name"])) % 90000 + 10000))

        body: dict[str, Any] = {
            "name": params["name"],
            "number": proj_num,
            "projectManager": pm_ref,
        }

        # startDate is required — default to today
        for date_field in ("startDate", "endDate"):
            if date_field in params:
                date_val = self.validate_date(params[date_field], date_field)
                if date_val:
                    body[date_field] = date_val
        if "startDate" not in body:
            body["startDate"] = dt_date.today().isoformat()

        for bool_field in ("isInternal", "isClosed"):
            if bool_field in params:
                body[bool_field] = params[bool_field]

        # Resolve customer by name if needed
        if "customer" in params:
            cust = params["customer"]
            if isinstance(cust, dict) and "id" not in cust:
                body["customer"] = _resolve_customer(api_client, cust)
            else:
                body["customer"] = self.ensure_ref(cust, "customer")

        if "department" in params:
            body["department"] = self.ensure_ref(params["department"], "department")

        body = self.strip_none_values(body)
        result = api_client.post("/project", data=body)
        value = result.get("value", {})
        logger.info("Created project id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class UpdateProjectHandler(BaseHandler):
    """GET /project/{id} then PUT /project/{id}. 2 API calls."""

    def get_task_type(self) -> str:
        return "update_project"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        # Resolve project by ID or name
        proj_id = params.get("projectId")
        if proj_id:
            proj_data = api_client.get(f"/project/{int(proj_id)}")
            project = proj_data.get("value", {})
        elif params.get("name"):
            search = api_client.get("/project", params={"name": params["name"], "count": 1})
            values = search.get("values", [])
            if values:
                project = values[0]
                proj_id = project["id"]
            else:
                # Project doesn't exist yet — create it
                create_handler = CreateProjectHandler()
                result = create_handler.execute(api_client, params)
                proj_id = result.get("id")
                if not proj_id:
                    return {"error": "project_creation_failed"}
                proj_data = api_client.get(f"/project/{proj_id}")
                project = proj_data.get("value", {})
        else:
            return {"error": "no_project_identifier"}

        if not project:
            return {"error": "project_not_found"}

        for field in ("name", "number", "isClosed", "isInternal"):
            if field in params:
                project[field] = params[field]

        # Fixed price — API field is lowercase "fixedprice", needs isFixedPrice=true
        if "fixedPrice" in params or "fixedprice" in params:
            price = params.get("fixedPrice") or params.get("fixedprice")
            project["fixedprice"] = price
            project["isFixedPrice"] = True

        for date_field in ("startDate", "endDate"):
            if date_field in params:
                date_val = self.validate_date(params[date_field], date_field)
                if date_val:
                    project[date_field] = date_val

        # Resolve customer by name if needed
        if "customer" in params:
            cust = params["customer"]
            if isinstance(cust, dict) and "id" not in cust:
                project["customer"] = _resolve_customer(api_client, cust)
            else:
                project["customer"] = self.ensure_ref(cust, "customer")

        # Resolve PM — create employee if needed
        if "projectManager" in params:
            pm = params["projectManager"]
            if isinstance(pm, dict) and "id" not in pm:
                _resolve_employee(api_client, pm)
            # Keep account owner as actual PM (they have PM access)

        if "department" in params:
            project["department"] = self.ensure_ref(params["department"], "department")

        # Strip readOnly/rate fields that cause 422 on PUT
        for readonly_field in (
            "projectRateTypes", "hourlyRates", "changes", "url",
            "displayName", "displayNameWithoutNumber",
        ):
            project.pop(readonly_field, None)

        result = api_client.put(f"/project/{proj_id}", data=project)
        logger.info("Updated project id=%s", proj_id)

        # Handle project invoicing: "invoice X% of fixed price"
        invoice_pct = params.get("invoicePercentage") or params.get("partialPaymentPercentage")
        fixed_price = params.get("fixedPrice") or params.get("fixedprice")
        if invoice_pct and fixed_price:
            invoice_amount = round(float(fixed_price) * float(invoice_pct) / 100, 2)
            customer_ref = project.get("customer")
            if customer_ref:
                from src.handlers.invoice import CreateInvoiceHandler

                inv_params = {
                    "customer": customer_ref,
                    "project": {"id": proj_id},
                    "orderLines": [
                        {
                            "description": f"Delbetaling {invoice_pct}%",
                            "unitPriceExcludingVatCurrency": invoice_amount,
                            "count": 1,
                        }
                    ],
                }
                try:
                    inv_handler = CreateInvoiceHandler()
                    inv_result = inv_handler.execute(api_client, inv_params)
                    logger.info("Created project invoice: %s", inv_result)
                except Exception as e:
                    logger.warning("Project invoice failed: %s", e)

        return {"id": proj_id, "action": "updated", "value": result.get("value", {})}


@register_handler
class LinkProjectCustomerHandler(BaseHandler):
    """GET /project/{id} then PUT /project/{id} with customer ref. 2 API calls."""

    def get_task_type(self) -> str:
        return "link_project_customer"

    @property
    def required_params(self) -> list[str]:
        return ["projectId", "customer"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        proj_id = int(params["projectId"])
        project = api_client.get(f"/project/{proj_id}")
        proj_data = project.get("value", {})
        if not proj_data:
            return {"error": "project_not_found"}

        proj_data["customer"] = self.ensure_ref(params["customer"], "customer")
        api_client.put(f"/project/{proj_id}", data=proj_data)
        logger.info("Linked customer to project id=%s", proj_id)
        return {"id": proj_id, "action": "customer_linked"}


@register_handler
class CreateActivityHandler(BaseHandler):
    """POST /activity with name and optional fields. 1 API call."""

    def get_task_type(self) -> str:
        return "create_activity"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": params["name"],
            "activityType": params.get("activityType", "GENERAL_ACTIVITY"),
        }

        for field in ("number", "description"):
            if field in params and params[field] is not None:
                body[field] = params[field]

        # isProjectActivity is readOnly — controlled via activityType

        body = self.strip_none_values(body)
        result = api_client.post("/activity", data=body)
        value = result.get("value", {})
        logger.info("Created activity id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}
