"""Shared order line building logic for orders and invoices.

Single source of truth for: product resolution, price field alias handling,
and order line payload construction.
"""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.entity_resolver import resolve as _resolve

logger = logging.getLogger(__name__)


def build_and_post_order_lines(
    api_client: TripletexClient,
    order_id: int,
    lines: list[dict[str, Any]],
) -> None:
    """Resolve products, normalize price aliases, POST order lines."""
    if not lines:
        return
    payloads = []
    for line in lines:
        ol: dict[str, Any] = {"order": {"id": order_id}}
        # Only resolve product if we don't already have price+description
        # (order lines work without product refs, saving a write call)
        price_keys = (
            "unitPriceExcludingVatCurrency",
            "priceExcludingVatCurrency",
            "amount",
            "price",
        )
        has_price = any(line.get(k) for k in price_keys)
        if "product" in line and not has_price:
            prod_val = line["product"]
            prod_num = line.get("productNumber") or line.get("number")
            if isinstance(prod_val, str) and prod_num:
                prod_val = {"name": prod_val, "number": prod_num}
            ol["product"] = _resolve(
                api_client,
                "product",
                prod_val,
                extra_create_fields={"price": 0},
            )
        elif "product" in line:
            # Use product name as description if no explicit description
            if "description" not in line:
                prod = line["product"]
                ol["description"] = prod.get("name") if isinstance(prod, dict) else str(prod)
        if "description" in line:
            ol["description"] = line["description"]
        ol["count"] = line.get("count", line.get("quantity", 1))
        if "unitPriceExcludingVatCurrency" in line:
            ol["unitPriceExcludingVatCurrency"] = line["unitPriceExcludingVatCurrency"]
        elif "priceExcludingVatCurrency" in line:
            ol["unitPriceExcludingVatCurrency"] = line["priceExcludingVatCurrency"]
        elif "amount" in line:
            ol["unitPriceExcludingVatCurrency"] = line["amount"]
        elif "price" in line:
            ol["unitPriceExcludingVatCurrency"] = line["price"]
        payloads.append({k: v for k, v in ol.items() if v is not None})
    if payloads:
        api_client.post("/order/orderline/list", data=payloads)
        logger.info("Added %d order lines to order %s", len(payloads), order_id)
