"""Travel expense handlers: create, deliver, and approve travel expenses."""

from __future__ import annotations

import contextlib
import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.handlers.resolvers import (
    find_cost_category as _find_cost_category,
)
from src.handlers.resolvers import (
    find_travel_expense as _find_travel_expense,
)
from src.handlers.resolvers import (
    get_travel_payment_type as _get_payment_type,
)
from src.handlers.resolvers import (
    resolve_employee as _resolve_employee,
)

logger = logging.getLogger(__name__)


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
        td = params.get("travelDetails", {})
        if not isinstance(td, dict):
            td = {}
        dep_date = (
            self.validate_date(
                params.get("departureDate") or td.get("departureDate"), "departureDate"
            )
            or today
        )
        ret_date = self.validate_date(
            params.get("returnDate") or td.get("returnDate"), "returnDate"
        )
        # Calculate return date from duration if not provided
        if not ret_date:
            from datetime import timedelta

            duration = td.get("duration") or td.get("numberOfDays") or params.get("numberOfDays")
            if isinstance(duration, (int, float)) and duration > 1:
                dep = dt_date.fromisoformat(dep_date)
                ret_date = (dep + timedelta(days=int(duration) - 1)).isoformat()
            else:
                ret_date = dep_date
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

        per_diem_keywords = {"per diem", "diett", "diet", "dagpenger"}
        for cost in costs:
            desc_lower = (cost.get("description") or "").lower()
            if cost.get("type") == "per_diem" or desc_lower in per_diem_keywords:
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
                td = params.get("travelDetails", {})
                duration = td.get("duration") if isinstance(td, dict) else None
                duration_days = (
                    duration.get("days")
                    if isinstance(duration, dict)
                    else duration
                    if isinstance(duration, (int, float))
                    else None
                )
                days = (
                    per_diem.get("days")
                    or per_diem.get("numberOfDays")
                    or per_diem.get("count")
                    or (td.get("numberOfDays") if isinstance(td, dict) else None)
                    or duration_days
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
