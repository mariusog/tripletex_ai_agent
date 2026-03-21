"""Module and role handlers: enable modules and assign roles via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler

logger = logging.getLogger(__name__)


@register_handler
class EnableModuleHandler(BaseHandler):
    """Enable a Tripletex module via PUT /modules.

    Some task types require specific modules to be enabled first.
    The module name is mapped to the corresponding API field.
    """

    tier = 1
    description = "Enable a Tripletex module"
    param_schema = {"moduleName": ParamSpec(description="Module field name to enable")}

    def get_task_type(self) -> str:
        return "enable_module"

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

    Finds employee by name/ID, updates userType or entitlements.
    """

    tier = 1
    description = "Assign a role to an employee"
    param_schema = {
        "employee": ParamSpec(description="Employee name, ID, or {firstName, lastName}"),
        "role": ParamSpec(required=False, description="administrator/standard/no_access"),
        "userType": ParamSpec(required=False),
    }

    def get_task_type(self) -> str:
        return "assign_role"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from src.handlers.entity_resolver import resolve as _resolve

        emp_param = params["employee"]

        # Find employee by ID or name
        if isinstance(emp_param, int) or (isinstance(emp_param, str) and emp_param.isdigit()):
            emp_data = api_client.get(f"/employee/{int(emp_param)}", fields="*")
            employee = emp_data.get("value", {})
        elif isinstance(emp_param, dict):
            emp_ref = _resolve(api_client, "employee", emp_param)
            emp_data = api_client.get(f"/employee/{emp_ref['id']}", fields="*")
            employee = emp_data.get("value", {})
        else:
            parts = str(emp_param).strip().split()
            search_params: dict[str, Any] = {"count": 5}
            if parts:
                search_params["firstName"] = parts[0]
            if len(parts) > 1:
                search_params["lastName"] = parts[-1]
            resp = api_client.get("/employee", params=search_params, fields="*")
            values = resp.get("values", [])
            if not values:
                return {"error": "employee_not_found"}
            employee = values[0]

        emp_id = employee.get("id")
        if not emp_id:
            return {"error": "employee_not_found"}

        role = params.get("role", "")
        role_lower = role.lower() if role else ""

        # Map role names to Tripletex userType / fields
        if role_lower in ("administrator", "admin"):
            employee["userType"] = "ADMINISTRATOR"
        elif role_lower in ("standard", "user"):
            employee["userType"] = "STANDARD"
        elif role_lower in ("no_access", "noaccess"):
            employee["userType"] = "NO_ACCESS"

        if "userType" in params:
            employee["userType"] = params["userType"]

        # Handle entitlements if provided
        if "roles" in params:
            employee["roles"] = params["roles"]
        if "entitlements" in params:
            employee["entitlements"] = params["entitlements"]

        # Set common access flags based on role
        if role_lower:
            employee["allowInformationRegistration"] = True

        if not employee.get("dateOfBirth"):
            employee["dateOfBirth"] = "1990-01-01"

        result = api_client.put(f"/employee/{emp_id}", data=employee)
        value = result.get("value", {}) if result else {}
        logger.info("Assigned role '%s' to employee id=%s", role, emp_id)
        return {"id": emp_id, "role": role, "action": "role_assigned", "value": value}
