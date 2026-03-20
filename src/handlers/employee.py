"""Employee handlers: create and update employees via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
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

        # Determine userType: STANDARD needs email, NO_ACCESS doesn't
        has_email = bool(params.get("email"))
        user_type = params.get("userType", "STANDARD" if has_email else "NO_ACCESS")

        body: dict[str, Any] = {
            "firstName": params["firstName"],
            "lastName": params["lastName"],
            "userType": user_type,
            "dateOfBirth": self.validate_date(params.get("dateOfBirth"), "dateOfBirth") or "1990-01-01",
        }

        for field in ("email", "phoneNumberMobile"):
            if params.get(field):
                body[field] = params[field]

        if "department" in params:
            body["department"] = self.ensure_ref(params["department"], "department")

        # Employment record
        start_date = self.validate_date(params.get("startDate"), "startDate") or today
        body["employments"] = [{
            "startDate": start_date,
            "employmentDetails": [{
                "date": start_date,
                "employmentType": params.get("employmentType", "ORDINARY"),
                "percentageOfFullTimeEquivalent": params.get("percentageOfFullTimeEquivalent", 100),
            }],
        }]

        body = self.strip_none_values(body)

        # Try creating — if it fails due to missing department, add one and retry
        try:
            result = api_client.post("/employee", data=body)
        except TripletexApiError as e:
            err_fields = [m.get("field", "") for m in e.error.validation_messages]
            if "department.id" in err_fields and "department" not in body:
                dept = api_client.get("/department", params={"count": 1}, fields="id")
                dept_vals = dept.get("values", [])
                if dept_vals:
                    body["department"] = {"id": dept_vals[0]["id"]}
                result = api_client.post("/employee", data=body)
            else:
                raise

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
