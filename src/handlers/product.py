"""Product handler: create products via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateProductHandler(BaseHandler):
    """POST /product with extracted fields. 1 API call."""

    def get_task_type(self) -> str:
        return "create_product"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {"name": params["name"]}

        for field in (
            "number",
            "costExcludingVatCurrency",
            "priceExcludingVatCurrency",
            "priceIncludingVatCurrency",
        ):
            if field in params and params[field] is not None:
                body[field] = params[field]

        # vatType, account, department are object references
        for ref_field in ("vatType", "account", "department"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        body = self.strip_none_values(body)
        result = api_client.post("/product", data=body)
        value = result.get("value", {})
        logger.info("Created product id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}
