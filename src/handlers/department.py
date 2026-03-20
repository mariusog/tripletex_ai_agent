"""Department handler: create departments via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateDepartmentHandler(BaseHandler):
    """POST /department with extracted fields. 1 API call."""

    def get_task_type(self) -> str:
        return "create_department"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        # Handle multi-department creation: "create departments X, Y, Z"
        departments = params.get("departments", [])
        if not departments:
            departments = [params]

        # Build bodies for all departments
        bodies = []
        for dept in departments:
            if isinstance(dept, str):
                dept = {"name": dept}
            name = dept.get("name", params.get("name", ""))
            if not name:
                continue

            body: dict[str, Any] = {"name": name}

            dept_num = dept.get("departmentNumber", params.get("departmentNumber"))
            if dept_num is not None:
                body["departmentNumber"] = str(dept_num)

            mgr = dept.get("departmentManager", params.get("departmentManager"))
            if mgr:
                if isinstance(mgr, dict) and "id" not in mgr:
                    from src.handlers.travel import _resolve_employee

                    body["departmentManager"] = _resolve_employee(api_client, mgr)
                else:
                    body["departmentManager"] = self.ensure_ref(mgr, "departmentManager")

            bodies.append(self.strip_none_values(body))

        if not bodies:
            return {"error": "no_departments"}

        # Use batch endpoint for multiple, single POST for one
        if len(bodies) == 1:
            result = api_client.post("/department", data=bodies[0])
            values = [result.get("value", {})]
        else:
            result = api_client.post("/department/list", data=bodies)
            values = result.get("values", []) if result else []

        created_ids = [v.get("id") for v in values if v.get("id")]
        logger.info("Created %d departments: %s", len(created_ids), created_ids)

        first_id = created_ids[0] if created_ids else None
        return {"id": first_id, "ids": created_ids, "action": "created"}
