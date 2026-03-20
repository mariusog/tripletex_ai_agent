"""Travel expense handlers: create, deliver, and approve travel expenses."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)

# Map common cost descriptions to Tripletex costCategory descriptions
COST_CATEGORY_MAP = {
    "fly": "Fly",
    "flybillett": "Fly",
    "flight": "Fly",
    "taxi": "Taxi",
    "hotell": "Hotell",
    "hotel": "Hotell",
    "mat": "Mat",
    "food": "Mat",
    "parkering": "Parkering",
    "parking": "Parkering",
    "buss": "Buss",
    "bus": "Buss",
    "tog": "Tog",
    "train": "Tog",
    "drivstoff": "Drivstoff",
    "fuel": "Drivstoff",
    "ferge": "Ferge",
    "ferry": "Ferge",
    "kollektiv": "Kollektivtransport",
    "public transport": "Kollektivtransport",
}


def _resolve_employee(
    api_client: TripletexClient, employee: Any
) -> dict[str, int]:
    """Resolve employee to {"id": N}. Searches by name or creates."""
    if isinstance(employee, dict) and "id" in employee:
        return {"id": int(employee["id"])}
    if isinstance(employee, (int, float)):
        return {"id": int(employee)}
    try:
        return {"id": int(employee)}
    except (TypeError, ValueError):
        pass

    first = ""
    last = ""
    email = None
    if isinstance(employee, dict):
        first = employee.get("firstName", "")
        last = employee.get("lastName", "")
        email = employee.get("email")
    elif isinstance(employee, str):
        parts = employee.strip().split()
        first = parts[0] if parts else ""
        last = parts[-1] if len(parts) > 1 else ""

    # Search by name
    search_params: dict[str, Any] = {"count": 1}
    if first:
        search_params["firstName"] = first
    if last:
        search_params["lastName"] = last
    resp = api_client.get("/employee", params=search_params, fields="id")
    values = resp.get("values", [])
    if values:
        return {"id": values[0]["id"]}

    # Create employee via handler (handles dept, employment, etc.)
    from src.handlers import HANDLER_REGISTRY

    emp_handler = HANDLER_REGISTRY["create_employee"]
    emp_params: dict[str, Any] = {
        "firstName": first or "Unknown",
        "lastName": last or "Employee",
    }
    if email:
        emp_params["email"] = email

    try:
        result = emp_handler.execute(api_client, emp_params)
        emp_id = result.get("id")
        logger.info("Auto-created employee '%s %s' id=%s", first, last, emp_id)
        return {"id": emp_id}
    except TripletexApiError as e:
        logger.warning("Failed to create employee: %s", e)
        return {"id": 0}


def _find_cost_category(
    api_client: TripletexClient,
    description: str,
    _cache: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, int] | None:
    """Find a cost category matching the description."""
    if _cache is None:
        _cache = {}
    if "categories" not in _cache:
        resp = api_client.get(
            "/travelExpense/costCategory",
            params={"showOnTravelExpenses": "true", "count": 50},
            fields="id,description",
        )
        _cache["categories"] = resp.get("values", [])

    desc_lower = description.lower().strip()
    # Direct map
    mapped = COST_CATEGORY_MAP.get(desc_lower)

    for cat in _cache["categories"]:
        cat_desc = cat.get("description", "").lower()
        if mapped and cat_desc == mapped.lower():
            return {"id": cat["id"]}
        if desc_lower in cat_desc or cat_desc in desc_lower:
            return {"id": cat["id"]}

    # Fallback: first category
    if _cache["categories"]:
        return {"id": _cache["categories"][0]["id"]}
    return None


def _get_payment_type(api_client: TripletexClient) -> dict[str, int] | None:
    """Get the first available travel payment type."""
    resp = api_client.get(
        "/travelExpense/paymentType",
        params={"count": 1},
        fields="id",
    )
    values = resp.get("values", [])
    if values:
        return {"id": values[0]["id"]}
    return None


@register_handler
class CreateTravelExpenseHandler(BaseHandler):
    """Create travel expense, add costs and per diem compensations."""

    def get_task_type(self) -> str:
        return "create_travel_expense"

    @property
    def required_params(self) -> list[str]:
        return ["employee"]

    def execute(
        self, api_client: TripletexClient, params: dict[str, Any]
    ) -> dict[str, Any]:
        today = dt_date.today().isoformat()

        # Step 1: Resolve employee
        employee_ref = _resolve_employee(api_client, params["employee"])

        # Step 2: Create travel expense
        body: dict[str, Any] = {
            "employee": employee_ref,
            "title": params.get("title", "Reise"),
        }
        for date_field in ("departureDate", "returnDate"):
            if date_field in params:
                date_val = self.validate_date(params[date_field], date_field)
                if date_val:
                    body[date_field] = date_val

        for ref_field in ("project", "department"):
            if ref_field in params:
                body[ref_field] = self.ensure_ref(params[ref_field], ref_field)

        body = self.strip_none_values(body)
        result = api_client.post("/travelExpense", data=body)
        te_id = result.get("value", {}).get("id")
        logger.info("Created travel expense id=%s", te_id)

        if not te_id:
            return {"error": "travel_expense_creation_failed"}

        # Step 3: Add costs
        costs = params.get("costs", [])
        payment_type = _get_payment_type(api_client)
        cat_cache: dict[str, list[dict[str, Any]]] = {}

        for cost in costs:
            if cost.get("type") == "per_diem":
                continue  # Handle per diem separately
            try:
                cost_body: dict[str, Any] = {
                    "travelExpense": {"id": te_id},
                    "date": cost.get("date") or today,
                    "amountCurrencyIncVat": cost.get(
                        "amount", cost.get("amountCurrencyIncVat", 0)
                    ),
                    "currency": {"id": 1},  # NOK
                }
                if payment_type:
                    cost_body["paymentType"] = payment_type
                desc = cost.get("description", "")
                cat = _find_cost_category(api_client, desc, cat_cache)
                if cat:
                    cost_body["costCategory"] = cat
                api_client.post("/travelExpense/cost", data=cost_body)
                logger.info("Added cost '%s' to travel expense %s", desc, te_id)
            except TripletexApiError as e:
                logger.warning("Failed to add cost: %s", e)

        # Step 4: Add per diem if mentioned
        per_diem = params.get("travelDetails", {}).get("perDiem")
        if not per_diem:
            # Check costs for per_diem type
            for cost in costs:
                if cost.get("type") == "per_diem":
                    per_diem = cost
                    break

        if per_diem:
            try:
                pd_body: dict[str, Any] = {
                    "travelExpense": {"id": te_id},
                    "count": per_diem.get(
                        "days",
                        params.get("travelDetails", {})
                        .get("duration", {})
                        .get("days", 1),
                    ),
                    "rate": per_diem.get("dailyRate", per_diem.get("amount", 0)),
                }
                api_client.post(
                    "/travelExpense/perDiemCompensation", data=pd_body
                )
                logger.info("Added per diem to travel expense %s", te_id)
            except TripletexApiError as e:
                logger.warning("Failed to add per diem: %s", e)

        return {"id": te_id, "action": "created"}


@register_handler
class DeliverTravelExpenseHandler(BaseHandler):
    """POST /travelExpense/:deliver."""

    def get_task_type(self) -> str:
        return "deliver_travel_expense"

    @property
    def required_params(self) -> list[str]:
        return ["travelExpenseId"]

    def execute(
        self, api_client: TripletexClient, params: dict[str, Any]
    ) -> dict[str, Any]:
        te_id = int(params["travelExpenseId"])
        api_client.put(
            f"/travelExpense/{te_id}/:deliver", data={"id": te_id}
        )
        logger.info("Delivered travel expense id=%s", te_id)
        return {"id": te_id, "action": "delivered"}


@register_handler
class ApproveTravelExpenseHandler(BaseHandler):
    """POST /travelExpense/:approve."""

    def get_task_type(self) -> str:
        return "approve_travel_expense"

    @property
    def required_params(self) -> list[str]:
        return ["travelExpenseId"]

    def execute(
        self, api_client: TripletexClient, params: dict[str, Any]
    ) -> dict[str, Any]:
        te_id = int(params["travelExpenseId"])
        api_client.put(
            f"/travelExpense/{te_id}/:approve", data={"id": te_id}
        )
        logger.info("Approved travel expense id=%s", te_id)
        return {"id": te_id, "action": "approved"}
