"""Order handler: create orders with order lines via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.handlers.resolvers import resolve_customer as _resolve_customer
from src.handlers.resolvers import resolve_product as _resolve_product

logger = logging.getLogger(__name__)


@register_handler
class CreateOrderHandler(BaseHandler):
    """POST /order then POST /order/orderline/list for line items."""

    def get_task_type(self) -> str:
        return "create_order"

    @property
    def required_params(self) -> list[str]:
        return ["customer"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        customer_ref = _resolve_customer(api_client, params.get("customer"))
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

        # Add order lines if provided
        lines = params.get("orderLines", params.get("lines", []))
        if lines and order_id:
            payloads = []
            for line in lines:
                ol: dict[str, Any] = {"order": {"id": order_id}}
                if "product" in line:
                    line_price = (
                        line.get("unitPriceExcludingVatCurrency")
                        or line.get("amount")
                        or line.get("price")
                    )
                    ol["product"] = _resolve_product(api_client, line["product"], price=line_price)
                if "description" in line:
                    ol["description"] = line["description"]
                ol["count"] = line.get("count", line.get("quantity", 1))
                if "unitPriceExcludingVatCurrency" in line:
                    ol["unitPriceExcludingVatCurrency"] = line["unitPriceExcludingVatCurrency"]
                elif "amount" in line:
                    ol["unitPriceExcludingVatCurrency"] = line["amount"]
                elif "price" in line:
                    ol["unitPriceExcludingVatCurrency"] = line["price"]
                payloads.append(self.strip_none_values(ol))
            if payloads:
                api_client.post("/order/orderline/list", data=payloads)
                logger.info("Added %d order lines", len(payloads))

        return {"id": order_id, "action": "created"}
