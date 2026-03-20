"""Department handlers: create and update departments via Tripletex API."""

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
        # Handle batch creation via "items" array
        items = params.get("items", [])
        if items:
            ids = []
            for item in items:
                merged = {**params, **item}
                merged.pop("items", None)
                result = self._create_one(api_client, merged)
                if result.get("id"):
                    ids.append(result["id"])
            return {"ids": ids, "action": "created", "count": len(ids)}

        return self._create_one(api_client, params)

    def _create_one(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"name": params["name"]}

        if "departmentNumber" in params and params["departmentNumber"] is not None:
            body["departmentNumber"] = str(params["departmentNumber"])

        if "departmentManager" in params:
            mgr = params["departmentManager"]
            if isinstance(mgr, dict) and "id" not in mgr:
                from src.handlers.resolvers import resolve_employee as _resolve_employee

                body["departmentManager"] = _resolve_employee(api_client, mgr)
            else:
                body["departmentManager"] = self.ensure_ref(mgr, "departmentManager")

        body = self.strip_none_values(body)
        result = api_client.post("/department", data=body)
        value = result.get("value", {})
        logger.info("Created department id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class UpdateDepartmentHandler(BaseHandler):
    """GET /department (search) then PUT /department/{id}. 2 API calls."""

    def get_task_type(self) -> str:
        return "update_department"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        name = params["name"]
        search = api_client.get("/department", params={"name": name, "count": 5}, fields="*")
        values = search.get("values", [])
        dept = None
        for v in values:
            if v.get("name", "").strip().lower() == name.strip().lower():
                dept = v
                break
        if not dept:
            dept = values[0] if values else None
        if not dept:
            return {"error": "not_found"}

        dept_id = dept["id"]

        if "newName" in params:
            dept["name"] = params["newName"]
        if "departmentNumber" in params:
            dept["departmentNumber"] = str(params["departmentNumber"])
        if "departmentManager" in params:
            mgr = params["departmentManager"]
            if isinstance(mgr, dict) and "id" not in mgr:
                from src.handlers.resolvers import resolve_employee as _resolve_employee

                dept["departmentManager"] = _resolve_employee(api_client, mgr)
            else:
                dept["departmentManager"] = self.ensure_ref(mgr, "departmentManager")

        result = api_client.put(f"/department/{dept_id}", data=dept)
        logger.info("Updated department id=%s", dept_id)
        return {"id": dept_id, "action": "updated", "value": result.get("value", {})}
