"""Travel expense handlers: create, deliver, and approve travel expenses."""

from __future__ import annotations

import contextlib
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


def _resolve_employee(api_client: TripletexClient, employee: Any) -> dict[str, int]:
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

    # Search by name (verify exact match — API search can be fuzzy)
    search_params: dict[str, Any] = {"count": 5}
    if first:
        search_params["firstName"] = first
    if last:
        search_params["lastName"] = last
    resp = api_client.get("/employee", params=search_params, fields="id,firstName,lastName")
    values = resp.get("values", [])
    for v in values:
        v_first = (v.get("firstName") or "").strip().lower()
        v_last = (v.get("lastName") or "").strip().lower()
        if v_first == first.strip().lower() and v_last == last.strip().lower():
            return {"id": v["id"]}

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

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today().isoformat()

        # Step 1: Resolve employee
        employee_ref = _resolve_employee(api_client, params["employee"])

        # Step 2: Create travel expense
        body: dict[str, Any] = {
            "employee": employee_ref,
            "title": params.get("title", "Reise"),
        }

        # Include travelDetails to make it a proper travel expense (type=0)
        # Without this, it's an employee expense (type=1) which doesn't support per diem
        td = params.get("travelDetails", {})
        dep_date = (
            self.validate_date(
                params.get("departureDate") or td.get("departureDate"), "departureDate"
            )
            or today
        )
        ret_date = (
            self.validate_date(params.get("returnDate") or td.get("returnDate"), "returnDate")
            or today
        )
        body["travelDetails"] = {
            "departureDate": dep_date,
            "returnDate": ret_date,
            "destination": td.get("destination", ""),
            "purpose": td.get("purpose", params.get("title", "")),
        }

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
                    "amountCurrencyIncVat": cost.get("amount", cost.get("amountCurrencyIncVat", 0)),
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
        per_diem = params.get("perDiem") or params.get("travelDetails", {}).get("perDiem")
        if not per_diem:
            # Check costs for per_diem type
            for cost in costs:
                if cost.get("type") == "per_diem":
                    per_diem = cost
                    break

        if per_diem:
            try:
                days = (
                    per_diem.get("days")
                    or per_diem.get("numberOfDays")
                    or per_diem.get("count")
                    or params.get("travelDetails", {}).get("numberOfDays")
                    or params.get("travelDetails", {}).get("duration", {}).get("days")
                    or 1
                )
                rate = (
                    per_diem.get("dailyRate") or per_diem.get("rate") or per_diem.get("amount", 0)
                )
                location = (
                    per_diem.get("location")
                    or params.get("travelDetails", {}).get("destination")
                    or params.get("title", "Norge")
                )
                pd_body: dict[str, Any] = {
                    "travelExpense": {"id": te_id},
                    "count": days,
                    "rate": rate,
                    "location": location,
                    "overnightAccommodation": per_diem.get("overnightAccommodation", "HOTEL"),
                }
                api_client.post("/travelExpense/perDiemCompensation", data=pd_body)
                logger.info("Added per diem to travel expense %s", te_id)
            except TripletexApiError as e:
                logger.warning("Failed to add per diem: %s", e)

        return {"id": te_id, "action": "created"}


def _find_travel_expense(api_client: TripletexClient, params: dict[str, Any]) -> int | None:
    """Find travel expense by ID, title, or employee name."""
    if "travelExpenseId" in params:
        return int(params["travelExpenseId"])
    if "id" in params:
        return int(params["id"])
    # Search by employee and/or title
    search_params: dict[str, Any] = {"count": 5}
    if params.get("employeeId"):
        search_params["employeeId"] = int(params["employeeId"])
    resp = api_client.get(
        "/travelExpense", params=search_params, fields="id,title,employee(id,firstName,lastName)"
    )
    values = resp.get("values", [])
    if not values:
        return None
    # Filter by title if provided
    title = params.get("title", "")
    if title:
        for v in values:
            if v.get("title", "").strip().lower() == title.strip().lower():
                return v["id"]
    # Filter by employee name if provided
    emp = params.get("employee")
    if emp and isinstance(emp, (str, dict)):
        first = ""
        last = ""
        if isinstance(emp, str):
            parts = emp.strip().split()
            first = parts[0].lower() if parts else ""
            last = parts[-1].lower() if len(parts) > 1 else ""
        elif isinstance(emp, dict):
            first = (emp.get("firstName") or "").lower()
            last = (emp.get("lastName") or "").lower()
        for v in values:
            ve = v.get("employee", {})
            vf = (ve.get("firstName") or "").strip().lower()
            vl = (ve.get("lastName") or "").strip().lower()
            if first and last and vf == first and vl == last:
                return v["id"]
            if first and vf == first:
                return v["id"]
    # Fallback: return the most recent
    return values[0]["id"] if values else None


@register_handler
class DeliverTravelExpenseHandler(BaseHandler):
    """POST /travelExpense/:deliver. Searches by employee/title if no ID."""

    def get_task_type(self) -> str:
        return "deliver_travel_expense"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        te_id = _find_travel_expense(api_client, params)
        if not te_id:
            # If we have employee info, create then deliver
            if params.get("employee"):
                create_handler = CreateTravelExpenseHandler()
                result = create_handler.execute(api_client, params)
                te_id = result.get("id")
            if not te_id:
                return {"error": "travel_expense_not_found"}
        api_client.put(f"/travelExpense/{te_id}/:deliver", data={"id": te_id})
        logger.info("Delivered travel expense id=%s", te_id)
        return {"id": te_id, "action": "delivered"}


@register_handler
class ApproveTravelExpenseHandler(BaseHandler):
    """POST /travelExpense/:approve. Searches by employee/title if no ID."""

    def get_task_type(self) -> str:
        return "approve_travel_expense"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        te_id = _find_travel_expense(api_client, params)
        if not te_id:
            # If we have employee info, create then approve
            if params.get("employee"):
                create_handler = CreateTravelExpenseHandler()
                result = create_handler.execute(api_client, params)
                te_id = result.get("id")
                if te_id:
                    with contextlib.suppress(TripletexApiError):
                        api_client.put(f"/travelExpense/{te_id}/:deliver", data={"id": te_id})
            if not te_id:
                return {"error": "travel_expense_not_found"}
        api_client.put(f"/travelExpense/{te_id}/:approve", data={"id": te_id})
        logger.info("Approved travel expense id=%s", te_id)
        return {"id": te_id, "action": "approved"}
