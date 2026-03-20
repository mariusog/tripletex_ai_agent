"""Project handlers: create projects, link customers, and create activities."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateProjectHandler(BaseHandler):
    """POST /project with extracted fields. 1 API call."""

    def get_task_type(self) -> str:
        return "create_project"

    @property
    def required_params(self) -> list[str]:
        return ["name", "number", "projectManager"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": params["name"],
            "number": params["number"],
            "projectManager": self.ensure_ref(params["projectManager"], "projectManager"),
        }

        for date_field in ("startDate", "endDate"):
            if date_field in params:
                date_val = self.validate_date(params[date_field], date_field)
                if date_val:
                    body[date_field] = date_val

        for bool_field in ("isInternal", "isClosed"):
            if bool_field in params:
                body[bool_field] = params[bool_field]

        for ref_field in ("department", "customer"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        body = self.strip_none_values(body)
        result = api_client.post("/project", data=body)
        value = result.get("value", {})
        logger.info("Created project id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class UpdateProjectHandler(BaseHandler):
    """GET /project/{id} then PUT /project/{id}. 2 API calls."""

    def get_task_type(self) -> str:
        return "update_project"

    @property
    def required_params(self) -> list[str]:
        return ["projectId"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        proj_id = int(params["projectId"])
        proj_data = api_client.get(f"/project/{proj_id}")
        project = proj_data.get("value", {})
        if not project:
            return {"error": "project_not_found"}

        for field in ("name", "number", "isClosed", "isInternal"):
            if field in params:
                project[field] = params[field]

        for date_field in ("startDate", "endDate"):
            if date_field in params:
                date_val = self.validate_date(params[date_field], date_field)
                if date_val:
                    project[date_field] = date_val

        for ref_field in ("projectManager", "department", "customer"):
            if ref_field in params:
                project[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        result = api_client.put(f"/project/{proj_id}", data=project)
        logger.info("Updated project id=%s", proj_id)
        return {"id": proj_id, "action": "updated", "value": result.get("value", {})}


@register_handler
class LinkProjectCustomerHandler(BaseHandler):
    """GET /project/{id} then PUT /project/{id} with customer ref. 2 API calls."""

    def get_task_type(self) -> str:
        return "link_project_customer"

    @property
    def required_params(self) -> list[str]:
        return ["projectId", "customer"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        proj_id = int(params["projectId"])
        project = api_client.get(f"/project/{proj_id}")
        proj_data = project.get("value", {})
        if not proj_data:
            return {"error": "project_not_found"}

        proj_data["customer"] = self.ensure_ref(params["customer"], "customer")
        api_client.put(f"/project/{proj_id}", data=proj_data)
        logger.info("Linked customer to project id=%s", proj_id)
        return {"id": proj_id, "action": "customer_linked"}


@register_handler
class CreateActivityHandler(BaseHandler):
    """POST /activity with name and optional fields. 1 API call."""

    def get_task_type(self) -> str:
        return "create_activity"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"name": params["name"]}

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
