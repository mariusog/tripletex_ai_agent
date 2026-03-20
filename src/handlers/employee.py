"""Employee handlers: create and update employees via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateEmployeeHandler(BaseHandler):
    """POST /employee with extracted fields. 1 API call."""

    def get_task_type(self) -> str:
        return "create_employee"

    @property
    def required_params(self) -> list[str]:
        return ["firstName", "lastName"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "firstName": params["firstName"],
            "lastName": params["lastName"],
        }
        for field in ("email", "phoneNumberMobile"):
            if params.get(field):
                body[field] = params[field]

        if "dateOfBirth" in params:
            date_val = self.validate_date(params["dateOfBirth"], "dateOfBirth")
            if date_val:
                body["dateOfBirth"] = date_val

        if "department" in params:
            body["department"] = self.ensure_ref(params["department"], "department")

        body = self.strip_none_values(body)
        result = api_client.post("/employee", data=body)
        value = result.get("value", {})
        logger.info("Created employee id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class UpdateEmployeeHandler(BaseHandler):
    """GET /employee (search by name) then PUT /employee/{id}. 2 API calls."""

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
        )
        values = search.get("values", [])
        if not values:
            logger.warning("Employee not found: %s %s", first, last)
            return {"error": "not_found"}

        employee = values[0]
        emp_id = employee["id"]

        # Merge updates onto existing employee
        for field in ("email", "phoneNumberMobile", "firstName", "lastName"):
            if params.get(field):
                employee[field] = params[field]

        if "dateOfBirth" in params:
            date_val = self.validate_date(params["dateOfBirth"], "dateOfBirth")
            if date_val:
                employee["dateOfBirth"] = date_val

        if "department" in params:
            employee["department"] = self.ensure_ref(params["department"], "department")

        result = api_client.put(f"/employee/{emp_id}", data=employee)
        logger.info("Updated employee id=%s", emp_id)
        return {"id": emp_id, "action": "updated", "value": result.get("value", {})}
