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

        # Resolve vatType — may be an ID, string description, or percentage
        if "vatType" in params:
            vat = params["vatType"]
            if isinstance(vat, (int, float)) or (isinstance(vat, str) and vat.isdigit()):
                body["vatType"] = {"id": int(vat)}
            elif isinstance(vat, dict) and "id" in vat:
                body["vatType"] = vat
            elif isinstance(vat, str):
                # Search by name/description
                try:
                    vat_resp = api_client.get_cached(
                        "vat_types",
                        "/ledger/vatType",
                        params={"count": 50},
                        fields="id,name,percentage",
                    )
                    vat_values = vat_resp.get("values", [])
                    vat_lower = vat.lower()
                    for v in vat_values:
                        v_name = (v.get("name") or "").lower()
                        if vat_lower in v_name or v_name in vat_lower:
                            body["vatType"] = {"id": v["id"]}
                            break
                except Exception:
                    logger.warning("Could not resolve vatType '%s'", vat)

        for ref_field in ("account", "department"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        body = self.strip_none_values(body)
        result = api_client.post("/product", data=body)
        value = result.get("value", {})
        logger.info("Created product id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}
