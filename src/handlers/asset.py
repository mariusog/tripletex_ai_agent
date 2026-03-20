"""Asset handlers: create and update assets via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class CreateAssetHandler(BaseHandler):
    """POST /asset with extracted fields."""

    def get_task_type(self) -> str:
        return "create_asset"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        body: dict[str, Any] = {"name": params["name"]}

        # Map common names to correct OpenAPI field names
        field_map = {
            "description": "description",
            "acquisitionDate": "dateOfAcquisition",
            "dateOfAcquisition": "dateOfAcquisition",
            "acquisitionCost": "acquisitionCost",
            "depreciationPercentage": "depreciationRate",
            "depreciationRate": "depreciationRate",
            "lifetime": "lifetime",
        }
        for param_name, api_name in field_map.items():
            if param_name in params:
                body[api_name] = params[param_name]
        # dateOfAcquisition is required
        if "dateOfAcquisition" not in body:
            body["dateOfAcquisition"] = dt_date.today().isoformat()

        for ref_field in ("account", "depreciationAccount", "department"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        result = api_client.post("/asset", data=body)
        value = result.get("value", {})
        logger.info("Created asset id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class UpdateAssetHandler(BaseHandler):
    """GET /asset/{id} then PUT /asset/{id} with updated fields."""

    def get_task_type(self) -> str:
        return "update_asset"

    @property
    def required_params(self) -> list[str]:
        return ["assetId"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        asset_id = int(params["assetId"])
        asset_data = api_client.get(f"/asset/{asset_id}")
        asset = asset_data.get("value", {})
        if not asset:
            return {"error": "asset_not_found"}

        for field in (
            "name",
            "description",
            "acquisitionDate",
            "acquisitionCost",
            "depreciationPercentage",
            "depreciationMonths",
            "lifetime",
        ):
            if field in params:
                asset[field] = params[field]

        for ref_field in ("account", "depreciationAccount", "department", "type"):
            if ref_field in params:
                asset[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        result = api_client.put(f"/asset/{asset_id}", data=asset)
        logger.info("Updated asset id=%s", asset_id)
        return {"id": asset_id, "action": "updated", "value": result.get("value", {})}
