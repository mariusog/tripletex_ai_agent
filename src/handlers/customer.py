"""Customer handlers: create and update customers via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateCustomerHandler(BaseHandler):
    """POST /customer with extracted fields. 1 API call."""

    def get_task_type(self) -> str:
        return "create_customer"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"name": params["name"]}
        for field in ("email", "phoneNumber", "organizationNumber", "invoiceEmail"):
            if params.get(field):
                body[field] = params[field]

        if params.get("deliveryAddress"):
            body["deliveryAddress"] = params["deliveryAddress"]

        body = self.strip_none_values(body)
        result = api_client.post("/customer", data=body)
        value = result.get("value", {})
        logger.info("Created customer id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class UpdateCustomerHandler(BaseHandler):
    """GET /customer (search by name) then PUT /customer/{id}. 2 API calls."""

    def get_task_type(self) -> str:
        return "update_customer"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        name = params["name"]
        search = api_client.get("/customer", params={"name": name, "count": 1})
        values = search.get("values", [])
        if not values:
            logger.warning("Customer not found: %s", name)
            return {"error": "not_found"}

        customer = values[0]
        cust_id = customer["id"]

        for field in ("name", "email", "phoneNumber", "organizationNumber", "invoiceEmail"):
            if params.get(field):
                customer[field] = params[field]

        if params.get("deliveryAddress"):
            customer["deliveryAddress"] = params["deliveryAddress"]

        result = api_client.put(f"/customer/{cust_id}", data=customer)
        logger.info("Updated customer id=%s", cust_id)
        return {"id": cust_id, "action": "updated", "value": result.get("value", {})}
