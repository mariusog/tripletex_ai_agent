"""Order handler: create orders with order lines via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler
from src.handlers.entity_resolver import resolve as _resolve
from src.services.order_line_builder import build_and_post_order_lines

logger = logging.getLogger(__name__)


@register_handler
class CreateOrderHandler(BaseHandler):
    """POST /order then POST /order/orderline/list for line items."""

    tier = 2
    description = "Create an order with order lines"
    param_schema = {
        "customer": ParamSpec(description="Customer name or ref"),
        "orderDate": ParamSpec(required=False, type="date"),
        "deliveryDate": ParamSpec(required=False, type="date"),
        "orderLines": ParamSpec(required=False, type="list", description="Line items"),
    }

    def get_task_type(self) -> str:
        return "create_order"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        customer_ref = _resolve(api_client, "customer", params.get("customer"))
        today = dt_date.today().isoformat()

        body: dict[str, Any] = {
            "customer": customer_ref,
            "orderDate": params.get("orderDate") or today,
            "deliveryDate": params.get("deliveryDate") or today,
        }

        for ref_field in ("department", "project"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        body = self.strip_none_values(body)
        result = api_client.post("/order", data=body)
        order = result.get("value", {})
        order_id = order.get("id")
        logger.info("Created order id=%s", order_id)

        lines = params.get("orderLines", params.get("lines", []))
        if lines and order_id:
            build_and_post_order_lines(api_client, order_id, lines)

        return {"id": order_id, "action": "created"}
