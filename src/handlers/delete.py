"""Delete handlers: config-driven search-then-delete for Tripletex entities."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import HANDLER_REGISTRY, BaseHandler

logger = logging.getLogger(__name__)


def _find_entity(
    api_client: TripletexClient,
    endpoint: str,
    params: dict[str, Any],
    search_field: str = "name",
) -> int | None:
    """Find entity ID by name or direct ID. Uses exact name matching."""
    if "id" in params:
        return int(params["id"])
    name = params.get(search_field, params.get("name", ""))
    if not name:
        return None
    try:
        resp = api_client.get(
            endpoint,
            params={search_field: name, "count": 5},
            fields="id," + search_field,
        )
        for v in resp.get("values", []):
            if str(v.get(search_field, "")).strip().lower() == str(name).strip().lower():
                return v["id"]
    except TripletexApiError:
        pass
    return None


def _do_delete(
    api_client: TripletexClient,
    path: str,
    entity_id: int,
    entity_type: str,
) -> dict[str, Any]:
    """Delete an entity with error handling."""
    try:
        api_client.delete(f"{path}/{entity_id}")
        logger.info("Deleted %s id=%s", entity_type, entity_id)
        return {"id": entity_id, "action": "deleted"}
    except TripletexApiError as e:
        logger.warning("Delete %s %s failed: %s", entity_type, entity_id, e)
        return {"id": entity_id, "error": str(e.error.message)}


# ---------------------------------------------------------------------------
# Custom find functions for entities with non-standard search logic
# ---------------------------------------------------------------------------


def _find_product(api_client: TripletexClient, params: dict[str, Any]) -> int | None:
    """Search product by id, number, then name."""
    if "id" in params:
        return int(params["id"])
    if "number" in params:
        resp = api_client.get(
            "/product",
            params={"number": str(params["number"]), "count": 1},
            fields="id",
        )
        vals = resp.get("values", [])
        if vals:
            return vals[0]["id"]
    return _find_entity(api_client, "/product", params)


def _find_travel_expense(api_client: TripletexClient, params: dict[str, Any]) -> int | None:
    """Search travel expense by id, travelExpenseId, or title."""
    if "id" in params or "travelExpenseId" in params:
        return int(params.get("id") or params["travelExpenseId"])
    if "title" in params:
        return _find_entity(api_client, "/travelExpense", params, search_field="title")
    return None


def _find_voucher(api_client: TripletexClient, params: dict[str, Any]) -> int | None:
    """Search voucher by id, voucherId, or number within current year."""
    if "id" in params or "voucherId" in params:
        return int(params.get("id") or params["voucherId"])
    today = dt_date.today()
    search: dict[str, Any] = {
        "dateFrom": f"{today.year}-01-01",
        "dateTo": today.isoformat(),
        "count": 10,
    }
    number = params.get("number") or params.get("voucherNumber")
    if number:
        search["number"] = str(number)
    try:
        resp = api_client.get("/ledger/voucher", params=search, fields="id,number")
        values = resp.get("values", [])
        if values:
            return values[0]["id"]
    except TripletexApiError:
        pass
    return None


# ---------------------------------------------------------------------------
# Config-driven delete handler
# ---------------------------------------------------------------------------


@dataclass
class DeleteEntityConfig:
    """Configuration for a delete handler."""

    entity_name: str
    endpoint: str
    search_field: str = "name"
    required: list[str] = field(default_factory=lambda: ["name"])
    custom_find: Callable[[TripletexClient, dict[str, Any]], int | None] | None = None
    tier: int = 1


class DeleteHandler(BaseHandler):
    """Generic delete handler, parameterized by DeleteEntityConfig."""

    def __init__(self, config: DeleteEntityConfig) -> None:
        self._config = config
        self.tier = config.tier
        self.description = f"Delete a {config.entity_name}"

    def get_task_type(self) -> str:
        return f"delete_{self._config.entity_name}"

    @property
    def required_params(self) -> list[str]:
        return self._config.required

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        if self._config.custom_find:
            eid = self._config.custom_find(api_client, params)
        else:
            eid = _find_entity(api_client, self._config.endpoint, params, self._config.search_field)
        if not eid:
            return {"error": "not_found"}
        return _do_delete(api_client, self._config.endpoint, eid, self._config.entity_name)


# ---------------------------------------------------------------------------
# Register all delete handlers
# ---------------------------------------------------------------------------

DELETE_CONFIGS = [
    DeleteEntityConfig("customer", "/customer"),
    DeleteEntityConfig("product", "/product", required=[], custom_find=_find_product),
    DeleteEntityConfig("department", "/department"),
    DeleteEntityConfig("project", "/project"),
    DeleteEntityConfig("order", "/order", required=["id"], tier=2),
    DeleteEntityConfig(
        "travel_expense", "/travelExpense", required=[], custom_find=_find_travel_expense, tier=2
    ),
    DeleteEntityConfig("supplier", "/supplier", tier=2),
    DeleteEntityConfig(
        "voucher", "/ledger/voucher", required=[], custom_find=_find_voucher, tier=3
    ),
]

for _config in DELETE_CONFIGS:
    _handler = DeleteHandler(_config)
    HANDLER_REGISTRY[_handler.get_task_type()] = _handler
