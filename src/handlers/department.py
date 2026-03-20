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
        body: dict[str, Any] = {"name": params["name"]}

        if "departmentNumber" in params and params["departmentNumber"] is not None:
            body["departmentNumber"] = params["departmentNumber"]

        if "departmentManager" in params:
            body["departmentManager"] = self.ensure_ref(
                params["departmentManager"], "departmentManager"
            )

        body = self.strip_none_values(body)
        result = api_client.post("/department", data=body)
        value = result.get("value", {})
        logger.info("Created department id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}
