"""Product handler: create products via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
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
            if isinstance(vat, dict) and "id" in vat:
                body["vatType"] = vat
            else:
                # Always search — numeric values like "25" are percentages, not IDs
                try:
                    vat_resp = api_client.get_cached(
                        "vat_types",
                        "/ledger/vatType",
                        params={"count": 50},
                        fields="id,name,percentage",
                    )
                    vat_values = vat_resp.get("values", [])
                    vat_str = str(vat).lower().strip().rstrip("%")
                    matched = False
                    # Match by percentage first (e.g. "25" or "25%")
                    try:
                        pct = float(vat_str)
                        for v in vat_values:
                            if v.get("percentage") == pct:
                                body["vatType"] = {"id": v["id"]}
                                matched = True
                                break
                    except ValueError:
                        pass
                    # Then match by name
                    if not matched:
                        for v in vat_values:
                            v_name = (v.get("name") or "").lower()
                            if vat_str in v_name or v_name in vat_str:
                                body["vatType"] = {"id": v["id"]}
                                break
                except Exception:
                    logger.warning("Could not resolve vatType '%s'", vat)

        for ref_field in ("account", "department"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        body = self.strip_none_values(body)
        try:
            result = api_client.post("/product", data=body)
        except TripletexApiError as e:
            # Retry without vatType if it caused the error
            if "vatType" in str(e) and "vatType" in body:
                del body["vatType"]
                result = api_client.post("/product", data=body)
            else:
                raise
        value = result.get("value", {})
        logger.info("Created product id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}
