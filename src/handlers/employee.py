"""Employee handlers: create and update employees via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateEmployeeHandler(BaseHandler):
    """POST /employee with extracted fields. Optimal: 1 API call."""

    def get_task_type(self) -> str:
        return "create_employee"

    @property
    def required_params(self) -> list[str]:
        return ["firstName", "lastName"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today().isoformat()

        # Determine userType: valid API values are STANDARD, EXTENDED, NO_ACCESS
        # ADMINISTRATOR/ADMIN -> EXTENDED (full admin access per OpenAPI spec)
        # STANDARD/EXTENDED require email for Visma Connect login
        has_email = bool(params.get("email"))
        raw_type = params.get("userType", "STANDARD" if has_email else "NO_ACCESS")
        is_admin = raw_type in ("ADMINISTRATOR", "ADMIN", "EXTENDED")
        user_type = "EXTENDED" if is_admin else ("STANDARD" if has_email else "NO_ACCESS")

        # STANDARD and EXTENDED require email
        if user_type in ("STANDARD", "EXTENDED") and not has_email:
            user_type = "NO_ACCESS"

        body: dict[str, Any] = {
            "firstName": params["firstName"],
            "lastName": params["lastName"],
            "userType": user_type,
            "dateOfBirth": (
                self.validate_date(params.get("dateOfBirth"), "dateOfBirth") or "1990-01-01"
            ),
        }

        # Set admin flag if requested
        if is_admin:
            body["allowInformationRegistration"] = True

        for field in ("email", "phoneNumberMobile"):
            if params.get(field):
                body[field] = params[field]

        # Always set department (required by API) — use provided or fetch first available
        if "department" in params:
            body["department"] = self.ensure_ref(params["department"], "department")
        else:
            dept = api_client.get_cached(
                "default_department", "/department", params={"count": 1}, fields="id"
            )
            dept_vals = dept.get("values", [])
            if dept_vals:
                body["department"] = {"id": dept_vals[0]["id"]}

        # Employment record
        start_date = self.validate_date(params.get("startDate"), "startDate") or today
        body["employments"] = [
            {
                "startDate": start_date,
                "employmentDetails": [
                    {
                        "date": start_date,
                        "employmentType": params.get("employmentType", "ORDINARY"),
                        "percentageOfFullTimeEquivalent": params.get(
                            "percentageOfFullTimeEquivalent", 100
                        ),
                    }
                ],
            }
        ]

        body = self.strip_none_values(body)
        result = api_client.post("/employee", data=body)

        value = result.get("value", {})
        logger.info("Created employee id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class UpdateEmployeeHandler(BaseHandler):
    """GET /employee (search) then PUT /employee/{id}. 2 API calls."""

    def get_task_type(self) -> str:
        return "update_employee"

    @property
    def required_params(self) -> list[str]:
        return ["firstName", "lastName"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        first = params["firstName"]
        last = params["lastName"]
        search = api_client.get(
            "/employee",
            params={"firstName": first, "lastName": last, "count": 1},
            fields="*",
        )
        values = search.get("values", [])
        if not values:
            logger.warning("Employee not found: %s %s", first, last)
            return {"error": "not_found"}

        employee = values[0]
        emp_id = employee["id"]

        for field in ("phoneNumberMobile", "firstName", "lastName"):
            if params.get(field):
                employee[field] = params[field]

        if "dateOfBirth" in params:
            date_val = self.validate_date(params["dateOfBirth"], "dateOfBirth")
            if date_val:
                employee["dateOfBirth"] = date_val
        if not employee.get("dateOfBirth"):
            employee["dateOfBirth"] = "1990-01-01"

        if "department" in params:
            employee["department"] = self.ensure_ref(params["department"], "department")

        result = api_client.put(f"/employee/{emp_id}", data=employee)
        logger.info("Updated employee id=%s", emp_id)
        return {"id": emp_id, "action": "updated", "value": result.get("value", {})}
