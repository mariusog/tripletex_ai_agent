"""Customer handlers: create and update customers via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateCustomerHandler(BaseHandler):
    """POST /customer with extracted fields. 1 API call."""

    tier = 1
    description = "Create a new customer"
    param_schema = {
        "name": ParamSpec(description="Customer name"),
        "email": ParamSpec(required=False),
        "phoneNumber": ParamSpec(required=False),
        "organizationNumber": ParamSpec(required=False),
    }

    def get_task_type(self) -> str:
        return "create_customer"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"name": params["name"]}

        for field in (
            "email",
            "phoneNumber",
            "phoneNumberMobile",
            "organizationNumber",
            "invoiceEmail",
            "isPrivateIndividual",
        ):
            if params.get(field):
                body[field] = params[field]

        # Also set email as invoiceEmail if not separately provided
        if body.get("email") and not body.get("invoiceEmail"):
            body["invoiceEmail"] = body["email"]

        # Address fields — Tripletex has postalAddress, physicalAddress, deliveryAddress
        for addr_field in ("postalAddress", "physicalAddress", "deliveryAddress"):
            if params.get(addr_field):
                body[addr_field] = params[addr_field]

        # Sometimes LLM extracts a flat "address" — map to postalAddress
        if params.get("address") and "postalAddress" not in body:
            addr = params["address"]
            if isinstance(addr, str):
                body["postalAddress"] = {"addressLine1": addr}
            elif isinstance(addr, dict):
                body["postalAddress"] = addr

        body = self.strip_none_values(body)
        result = api_client.post("/customer", data=body)
        value = result.get("value", {})
        logger.info("Created customer id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class UpdateCustomerHandler(BaseHandler):
    """GET /customer (search by name) then PUT /customer/{id}. 2 API calls."""

    tier = 1
    description = "Update an existing customer"
    param_schema = {"name": ParamSpec(description="Customer name to find")}

    def get_task_type(self) -> str:
        return "update_customer"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        name = params["name"]
        search = api_client.get("/customer", params={"name": name, "count": 5}, fields="*")
        values = search.get("values", [])
        # Exact match
        customer = None
        for v in values:
            if v.get("name", "").strip().lower() == name.strip().lower():
                customer = v
                break
        if not customer:
            if values:
                customer = values[0]
            else:
                logger.warning("Customer not found: %s", name)
                return {"error": "not_found"}

        cust_id = customer["id"]

        for field in (
            "name",
            "email",
            "phoneNumber",
            "phoneNumberMobile",
            "organizationNumber",
            "invoiceEmail",
        ):
            if params.get(field):
                customer[field] = params[field]

        for addr_field in ("postalAddress", "physicalAddress", "deliveryAddress"):
            if params.get(addr_field):
                customer[addr_field] = params[addr_field]

        result = api_client.put(f"/customer/{cust_id}", data=customer)
        logger.info("Updated customer id=%s", cust_id)
        return {
            "id": cust_id,
            "action": "updated",
            "value": result.get("value", {}),
        }
