"""Module and role handlers: enable modules and assign roles via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class EnableModuleHandler(BaseHandler):
    """Enable a Tripletex module via PUT /modules.

    Some task types require specific modules to be enabled first.
    The module name is mapped to the corresponding API field.
    """

    def get_task_type(self) -> str:
        return "enable_module"

    @property
    def required_params(self) -> list[str]:
        return ["moduleName"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        module_name = params["moduleName"]

        try:
            current = api_client.get("/modules")
            modules = current.get("value", {})
        except TripletexApiError as exc:
            logger.warning("Failed to fetch current modules: %s", exc)
            modules = {}

        # Set the module flag to True
        modules[module_name] = True

        # Additional module fields from params
        for field in ("moduleAccountingInternal", "moduleProject", "moduleDepartment"):
            if field in params:
                modules[field] = params[field]

        result = api_client.put("/modules", data=modules)
        value = result.get("value", {}) if result else {}
        logger.info("Enabled module %s", module_name)
        return {"moduleName": module_name, "action": "enabled", "value": value}


@register_handler
class AssignRoleHandler(BaseHandler):
    """Assign a role to an employee.

    GET /employee to find the employee, then PUT with updated role info.
    Roles in Tripletex are managed through employee entitlements.
    """

    def get_task_type(self) -> str:
        return "assign_role"

    @property
    def required_params(self) -> list[str]:
        return ["employee"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        emp_param = params["employee"]

        # Find employee by ID or name
        if isinstance(emp_param, int) or (isinstance(emp_param, str) and emp_param.isdigit()):
            emp_data = api_client.get(f"/employee/{int(emp_param)}")
            employee = emp_data.get("value", {})
        else:
            # Search by name
            search = api_client.get("/employee", params={"firstName": emp_param, "count": 1})
            values = search.get("values", [])
            if not values:
                return {"error": "employee_not_found"}
            employee = values[0]

        emp_id = employee.get("id")
        if not emp_id:
            return {"error": "employee_not_found"}

        # Set role via userType (roles/entitlements/allowInformationRegistration
        # are not writable fields per OpenAPI spec)
        role = params.get("role", "")
        if role.upper() in ("ADMIN", "ADMINISTRATOR", "EXTENDED"):
            employee["userType"] = "EXTENDED"
        elif role.upper() in ("STANDARD", "USER"):
            employee["userType"] = "STANDARD"

        result = api_client.put(f"/employee/{emp_id}", data=employee)
        value = result.get("value", {}) if result else {}
        logger.info("Assigned role '%s' to employee id=%s", role, emp_id)
        return {"id": emp_id, "role": role, "action": "role_assigned", "value": value}
