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
        body: dict[str, Any] = {"name": params["name"]}

        for field in (
            "description",
            "acquisitionDate",
            "acquisitionCost",
            "depreciationPercentage",
            "depreciationMonths",
            "lifetime",
            "assetNumber",
        ):
            if field in params:
                body[field] = params[field]

        for ref_field in ("account", "depreciationAccount", "department", "type"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        result = api_client.post("/asset", data=body)
        value = result.get("value", {})
        logger.info("Created asset id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class UpdateAssetHandler(BaseHandler):
    """Find asset by ID or name, then PUT with updated fields."""

    def get_task_type(self) -> str:
        return "update_asset"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        asset = None
        asset_id = None
        if "assetId" in params or "id" in params:
            asset_id = int(params.get("assetId") or params["id"])
            asset_data = api_client.get(f"/asset/{asset_id}")
            asset = asset_data.get("value", {})
        elif "name" in params:
            resp = api_client.get("/asset", params={"name": params["name"], "count": 5}, fields="*")
            for v in resp.get("values", []):
                if v.get("name", "").strip().lower() == params["name"].strip().lower():
                    asset = v
                    break
            if not asset and resp.get("values"):
                asset = resp["values"][0]
        if not asset:
            return {"error": "asset_not_found"}
        asset_id = asset["id"]

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
