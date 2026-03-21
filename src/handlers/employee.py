"""Employee handlers: create and update employees via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateEmployeeHandler(BaseHandler):
    """POST /employee with extracted fields. Optimal: 1 API call."""

    tier = 1
    description = "Create a new employee in Tripletex"
    param_schema = {
        "firstName": ParamSpec(description="Employee first name"),
        "lastName": ParamSpec(description="Employee last name"),
        "email": ParamSpec(required=False, description="Email address"),
        "phoneNumberMobile": ParamSpec(required=False, description="Mobile phone"),
        "userType": ParamSpec(required=False, description="STANDARD or ADMINISTRATOR"),
    }

    def get_task_type(self) -> str:
        return "create_employee"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today().isoformat()

        # Determine userType: STANDARD needs email, NO_ACCESS doesn't
        has_email = bool(params.get("email"))
        user_type = params.get("userType", "STANDARD" if has_email else "NO_ACCESS")

        body: dict[str, Any] = {
            "firstName": params["firstName"],
            "lastName": params["lastName"],
            "userType": user_type,
            "dateOfBirth": (
                self.validate_date(params.get("dateOfBirth"), "dateOfBirth") or "1990-01-01"
            ),
        }

        for field in ("email", "phoneNumberMobile"):
            if params.get(field):
                body[field] = params[field]

        if "department" in params:
            body["department"] = self.ensure_ref(params["department"], "department")
        else:
            # Pre-fetch department (required field) to avoid a wasted 422
            dept = api_client.get_cached(
                "default_dept", "/department", params={"count": 1}, fields="id"
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

        try:
            result = api_client.post("/employee", data=body)
        except TripletexApiError as e:
            err_msgs = [m.get("message", "") for m in e.error.validation_messages]
            # If email already exists, find the employee and return
            if any("e-post" in m.lower() or "email" in m.lower() for m in err_msgs):
                email = body.get("email")
                if email:
                    resp = api_client.get(
                        "/employee", params={"email": email, "count": 1}, fields="id"
                    )
                    vals = resp.get("values", [])
                    if vals:
                        logger.info("Employee with email %s exists id=%s", email, vals[0]["id"])
                        return {"id": vals[0]["id"], "action": "already_exists"}
            raise

        value = result.get("value", {})
        logger.info("Created employee id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class UpdateEmployeeHandler(BaseHandler):
    """GET /employee (search) then PUT /employee/{id}. 2 API calls."""

    tier = 1
    description = "Update an existing employee"
    param_schema = {
        "firstName": ParamSpec(description="First name to find employee"),
        "lastName": ParamSpec(description="Last name to find employee"),
    }

    def get_task_type(self) -> str:
        return "update_employee"

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
