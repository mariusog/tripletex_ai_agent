"""Travel expense handlers: create, deliver, and approve travel expenses."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateTravelExpenseHandler(BaseHandler):
    """POST /travelExpense with employee, project, costs, etc. 1 API call."""

    def get_task_type(self) -> str:
        return "create_travel_expense"

    @property
    def required_params(self) -> list[str]:
        return ["employee"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "employee": self.ensure_ref(params["employee"], "employee"),
        }

        if params.get("title"):
            body["title"] = params["title"]
        if params.get("description"):
            body["description"] = params["description"]

        for date_field in ("departureDate", "returnDate"):
            if date_field in params:
                date_val = self.validate_date(params[date_field], date_field)
                if date_val:
                    body[date_field] = date_val

        for ref_field in ("project", "department"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        for list_field in ("travelDetails", "costs", "perDiemCompensations"):
            if params.get(list_field):
                body[list_field] = params[list_field]

        body = self.strip_none_values(body)
        result = api_client.post("/travelExpense", data=body)
        value = result.get("value", {})
        logger.info("Created travel expense id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class DeliverTravelExpenseHandler(BaseHandler):
    """POST /travelExpense/:deliver. 1 API call."""

    def get_task_type(self) -> str:
        return "deliver_travel_expense"

    @property
    def required_params(self) -> list[str]:
        return ["travelExpenseId"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        te_id = int(params["travelExpenseId"])
        api_client.put(f"/travelExpense/{te_id}/:deliver", data={"id": te_id})
        logger.info("Delivered travel expense id=%s", te_id)
        return {"id": te_id, "action": "delivered"}


@register_handler
class ApproveTravelExpenseHandler(BaseHandler):
    """POST /travelExpense/:approve. 1 API call."""

    def get_task_type(self) -> str:
        return "approve_travel_expense"

    @property
    def required_params(self) -> list[str]:
        return ["travelExpenseId"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        te_id = int(params["travelExpenseId"])
        api_client.put(f"/travelExpense/{te_id}/:approve", data={"id": te_id})
        logger.info("Approved travel expense id=%s", te_id)
        return {"id": te_id, "action": "approved"}
