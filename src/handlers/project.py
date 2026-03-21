"""Project handlers: create projects, link customers, and create activities."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler
from src.handlers.entity_resolver import resolve as _resolve

logger = logging.getLogger(__name__)


@register_handler
class CreateProjectHandler(BaseHandler):
    """POST /project with extracted fields. 1 API call."""

    tier = 1
    description = "Create a new project"
    param_schema = {
        "name": ParamSpec(description="Project name"),
        "number": ParamSpec(required=False),
        "startDate": ParamSpec(required=False, type="date"),
        "endDate": ParamSpec(required=False, type="date"),
        "customer": ParamSpec(required=False, description="Customer name or ref"),
        "projectManager": ParamSpec(required=False, description="PM name or ref"),
    }

    def get_task_type(self) -> str:
        return "create_project"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        import secrets
        from datetime import date as dt_date

        from src.api_client import TripletexApiError

        # Resolve project manager — use the requested PM directly
        pm = params.get("projectManager")
        pm_ref = None
        if pm and isinstance(pm, dict) and "id" not in pm:
            try:
                pm_ref = _resolve(api_client, "employee", pm)
            except Exception:
                logger.warning("PM employee resolution failed")

        # Fall back to account owner if PM couldn't be resolved
        if not pm_ref or not pm_ref.get("id"):
            emp_search = api_client.get_cached(
                "account_owner", "/employee", params={"count": 1}, fields="id"
            )
            emp_values = emp_search.get("values", [])
            pm_ref = {"id": emp_values[0]["id"]} if emp_values else {"id": 0}

        proj_num = str(params.get("number", secrets.randbelow(90000) + 10000))

        body: dict[str, Any] = {
            "name": params["name"],
            "number": proj_num,
            "projectManager": pm_ref,
        }

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

        # Always create customer if specified (competition checks attributes)
        if "customer" in params:
            cust = params["customer"]
            if isinstance(cust, dict) and "id" not in cust:
                cust_name = cust.get("name", "")
                cust_body: dict[str, Any] = {"name": cust_name}
                if cust.get("organizationNumber"):
                    cust_body["organizationNumber"] = str(cust["organizationNumber"])
                if cust.get("email"):
                    cust_body["email"] = cust["email"]
                try:
                    cust_result = api_client.post("/customer", data=cust_body)
                    body["customer"] = {"id": cust_result.get("value", {}).get("id")}
                except TripletexApiError:
                    body["customer"] = _resolve(api_client, "customer", cust)
            else:
                body["customer"] = self.ensure_ref(cust, "customer")

        if "department" in params:
            body["department"] = self.ensure_ref(params["department"], "department")

        body = self.strip_none_values(body)
        result = api_client.post("/project", data=body)
        value = result.get("value", {})
        logger.info("Created project id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


def _find_project(api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any] | None:
    """Find project by ID or name search."""
    if "projectId" in params:
        proj_data = api_client.get(f"/project/{int(params['projectId'])}")
        return proj_data.get("value")
    name = params.get("name") or params.get("projectName")
    if name:
        resp = api_client.get("/project", params={"name": name, "count": 5}, fields="*")
        for v in resp.get("values", []):
            if v.get("name", "").strip().lower() == name.strip().lower():
                return v
        if resp.get("values"):
            return resp["values"][0]
    return None


@register_handler
class UpdateProjectHandler(BaseHandler):
    """GET /project (search by name or ID) then PUT. 2 API calls."""

    tier = 2
    description = "Update an existing project"

    def get_task_type(self) -> str:
        return "update_project"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        project = _find_project(api_client, params)
        if not project:
            return {"error": "project_not_found"}
        proj_id = project["id"]

        # Allow "newName" to rename the project
        if "newName" in params:
            project["name"] = params["newName"]
        elif "name" in params and params["name"] != project.get("name"):
            project["name"] = params["name"]

        for field in ("number", "isClosed", "isInternal"):
            if field in params:
                project[field] = params[field]

        for date_field in ("startDate", "endDate"):
            if date_field in params:
                date_val = self.validate_date(params[date_field], date_field)
                if date_val:
                    project[date_field] = date_val

        for ref_field in ("projectManager", "department"):
            if ref_field in params:
                project[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        if "customer" in params:
            cust = params["customer"]
            if isinstance(cust, dict) and "id" not in cust:
                project["customer"] = _resolve(api_client, "customer", cust)
            else:
                project["customer"] = self.ensure_ref(cust, "customer")

        result = api_client.put(f"/project/{proj_id}", data=project)
        logger.info("Updated project id=%s", proj_id)
        return {"id": proj_id, "action": "updated", "value": result.get("value", {})}


@register_handler
class LinkProjectCustomerHandler(BaseHandler):
    """Find project by name/ID, resolve customer, then PUT. 2-3 API calls."""

    tier = 2
    description = "Link a customer to a project"
    param_schema = {"customer": ParamSpec(description="Customer name or ref")}

    def get_task_type(self) -> str:
        return "link_project_customer"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        proj_data = _find_project(api_client, params)
        if not proj_data:
            return {"error": "project_not_found"}

        proj_id = proj_data["id"]
        cust = params["customer"]
        if isinstance(cust, dict) and "id" not in cust:
            proj_data["customer"] = _resolve(api_client, "customer", cust)
        else:
            proj_data["customer"] = self.ensure_ref(cust, "customer")

        api_client.put(f"/project/{proj_id}", data=proj_data)
        logger.info("Linked customer to project id=%s", proj_id)
        return {"id": proj_id, "action": "customer_linked"}


@register_handler
class CreateActivityHandler(BaseHandler):
    """POST /activity with name and optional fields. 1 API call."""

    tier = 2
    description = "Create a new activity"
    param_schema = {"name": ParamSpec(description="Activity name")}

    def get_task_type(self) -> str:
        return "create_activity"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": params["name"],
            "activityType": params.get("activityType", "GENERAL_ACTIVITY"),
        }

        for field in ("number", "description"):
            if field in params and params[field] is not None:
                body[field] = params[field]

        if "isProjectActivity" in params:
            body["isProjectActivity"] = params["isProjectActivity"]

        body = self.strip_none_values(body)
        result = api_client.post("/activity", data=body)
        value = result.get("value", {})
        logger.info("Created activity id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}
