"""Product handler: create products via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler

logger = logging.getLogger(__name__)


def _resolve_vat_type(api_client: TripletexClient, vat: Any) -> dict[str, int] | None:
    """Resolve vatType: handles percentage strings like '25', IDs, or dicts."""
    if isinstance(vat, dict) and "id" in vat:
        return {"id": int(vat["id"])}
    # Try interpreting as a percentage (e.g. "25" means 25% VAT)
    try:
        val = int(vat)
    except (TypeError, ValueError):
        return None
    # Common VAT percentages — look up by percentage first
    if val in (0, 6, 12, 15, 25):
        try:
            resp = api_client.get(
                "/ledger/vatType",
                params={"percentage": str(val), "count": 5},
                fields="id,percentage,name",
            )
            values = resp.get("values", [])
            # Prefer output VAT types (utgående mva)
            for v in values:
                name = (v.get("name") or "").lower()
                if "utgående" in name or "output" in name or "salg" in name:
                    return {"id": v["id"]}
            if values:
                return {"id": values[0]["id"]}
        except TripletexApiError:
            pass
    # Fall back to treating as an ID
    return {"id": val}


@register_handler
class CreateProductHandler(BaseHandler):
    """POST /product with extracted fields. 1 API call."""

    tier = 1
    description = "Create a new product"
    param_schema = {
        "name": ParamSpec(description="Product name"),
        "number": ParamSpec(required=False, description="Product number"),
        "priceExcludingVatCurrency": ParamSpec(required=False, type="number"),
        "vatType": ParamSpec(required=False, description="VAT type percentage or ID"),
    }

    def get_task_type(self) -> str:
        return "create_product"

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

        # vatType needs special resolution (percentage vs ID)
        if "vatType" in params:
            vat_ref = _resolve_vat_type(api_client, params["vatType"])
            if vat_ref:
                body["vatType"] = vat_ref

        for ref_field in ("account", "department"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        body = self.strip_none_values(body)
        try:
            result = api_client.post("/product", data=body)
        except TripletexApiError:
            # Retry without vatType if it caused the error
            body.pop("vatType", None)
            result = api_client.post("/product", data=body)
        value = result.get("value", {})
        logger.info("Created product id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}
