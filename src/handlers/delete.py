"""Delete handlers: search by name then delete entities via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler

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


@register_handler
class DeleteCustomerHandler(BaseHandler):
    def get_task_type(self) -> str:
        return "delete_customer"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        eid = _find_entity(api_client, "/customer", params)
        if not eid:
            return {"error": "not_found"}
        return _do_delete(api_client, "/customer", eid, "customer")


@register_handler
class DeleteProductHandler(BaseHandler):
    def get_task_type(self) -> str:
        return "delete_product"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        eid = None
        if "id" in params:
            eid = int(params["id"])
        elif "number" in params:
            resp = api_client.get(
                "/product",
                params={"number": str(params["number"]), "count": 1},
                fields="id",
            )
            vals = resp.get("values", [])
            if vals:
                eid = vals[0]["id"]
        if not eid:
            eid = _find_entity(api_client, "/product", params)
        if not eid:
            return {"error": "not_found"}
        return _do_delete(api_client, "/product", eid, "product")


@register_handler
class DeleteDepartmentHandler(BaseHandler):
    def get_task_type(self) -> str:
        return "delete_department"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        eid = _find_entity(api_client, "/department", params)
        if not eid:
            return {"error": "not_found"}
        return _do_delete(api_client, "/department", eid, "department")


@register_handler
class DeleteProjectHandler(BaseHandler):
    def get_task_type(self) -> str:
        return "delete_project"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        eid = _find_entity(api_client, "/project", params)
        if not eid:
            return {"error": "not_found"}
        return _do_delete(api_client, "/project", eid, "project")


@register_handler
class DeleteOrderHandler(BaseHandler):
    def get_task_type(self) -> str:
        return "delete_order"

    @property
    def required_params(self) -> list[str]:
        return ["id"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        eid = int(params["id"])
        return _do_delete(api_client, "/order", eid, "order")


@register_handler
class DeleteTravelExpenseHandler(BaseHandler):
    def get_task_type(self) -> str:
        return "delete_travel_expense"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        eid = None
        if "id" in params or "travelExpenseId" in params:
            eid = int(params.get("id") or params["travelExpenseId"])
        elif "title" in params:
            eid = _find_entity(api_client, "/travelExpense", params, search_field="title")
        if not eid:
            return {"error": "not_found"}
        return _do_delete(api_client, "/travelExpense", eid, "travel_expense")


@register_handler
class DeleteSupplierHandler(BaseHandler):
    def get_task_type(self) -> str:
        return "delete_supplier"

    @property
    def required_params(self) -> list[str]:
        return ["name"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        eid = _find_entity(api_client, "/supplier", params)
        if not eid:
            return {"error": "not_found"}
        return _do_delete(api_client, "/supplier", eid, "supplier")


@register_handler
class DeleteVoucherHandler(BaseHandler):
    def get_task_type(self) -> str:
        return "delete_voucher"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        eid = None
        if "id" in params or "voucherId" in params:
            eid = int(params.get("id") or params["voucherId"])
        if not eid:
            # Search by voucher number
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
                    eid = values[0]["id"]
            except TripletexApiError:
                pass
        if not eid:
            return {"error": "not_found"}
        return _do_delete(api_client, "/ledger/voucher", eid, "voucher")
