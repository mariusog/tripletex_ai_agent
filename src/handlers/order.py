"""Order handler: create orders with order lines via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateOrderHandler(BaseHandler):
    """POST /order then POST /order/orderline/list for line items.

    Optimal: 1 call (no lines) or 2 calls (with lines, always batch).
    """

    def get_task_type(self) -> str:
        return "create_order"

    @property
    def required_params(self) -> list[str]:
        return ["customer"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "customer": self.ensure_ref(params["customer"], "customer"),
        }

        for date_field in ("orderDate", "deliveryDate"):
            if date_field in params:
                date_val = self.validate_date(params[date_field], date_field)
                if date_val:
                    body[date_field] = date_val

        for field in ("receiver", "deliveryComment"):
            if params.get(field):
                body[field] = params[field]

        for ref_field in ("department", "project"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        body = self.strip_none_values(body)
        result = api_client.post("/order", data=body)
        order = result.get("value", {})
        order_id = order.get("id")
        logger.info("Created order id=%s", order_id)

        # Add order lines if provided — always use batch endpoint
        lines = params.get("orderLines", params.get("lines", []))
        line_ids = _create_order_lines(api_client, order_id, lines)

        return {"id": order_id, "action": "created", "orderLineIds": line_ids}


def _build_order_line(line: dict[str, Any], order_id: int) -> dict[str, Any]:
    """Build a single order line payload from extracted params."""
    ol: dict[str, Any] = {"order": {"id": order_id}}
    if "product" in line:
        ol["product"] = BaseHandler.ensure_ref(line["product"], "product")
    for field in ("description", "count", "unitPriceExcludingVatCurrency", "unitCostCurrency"):
        if field in line and line[field] is not None:
            ol[field] = line[field]
    if "vatType" in line:
        ol["vatType"] = BaseHandler.ensure_ref(line["vatType"], "vatType")
    return {k: v for k, v in ol.items() if v is not None}


def _create_order_lines(
    api_client: TripletexClient, order_id: int, lines: list[dict[str, Any]]
) -> list[int]:
    """Create order lines using batch endpoint. 1 API call for any number of lines."""
    if not lines or not order_id:
        return []
    payloads = [_build_order_line(line, order_id) for line in lines]
    # Always use batch endpoint — works for 1 or more lines, saves a conditional call
    resp = api_client.post("/order/orderline/list", data=payloads)
    values = resp.get("values", [])
    return [v.get("id") for v in values if v.get("id")]
