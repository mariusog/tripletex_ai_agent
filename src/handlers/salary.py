"""Salary/payroll handler: run payroll via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.handlers.resolvers import resolve_employee

logger = logging.getLogger(__name__)

# Map common salary description keywords to Tripletex salary type numbers
SALARY_TYPE_MAP = {
    "fastlønn": "1000",
    "fast lønn": "1000",
    "grunnlønn": "1000",
    "base salary": "1000",
    "base pay": "1000",
    "salaire de base": "1000",
    "gehalt": "1000",
    "grundgehalt": "1000",
    "salario base": "1000",
    "månedslönn": "1000",
    "månedslønn": "1000",
    "bonus": "1000",
    "prime": "1000",
    "tillegg": "1000",
    "overtime": "1000",
    "overtid": "1000",
}


def _find_salary_type(
    api_client: TripletexClient,
    description: str,
    cache: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, int] | None:
    """Find a salary type matching the description."""
    if cache is None:
        cache = {}
    if "types" not in cache:
        resp = api_client.get(
            "/salary/type",
            params={"count": 50, "isInactive": "false"},
            fields="id,number,name",
        )
        cache["types"] = resp.get("values", [])

    desc_lower = description.lower().strip()

    # Try mapped number first
    for keyword, number in SALARY_TYPE_MAP.items():
        if keyword in desc_lower:
            for st in cache["types"]:
                if str(st.get("number", "")) == number:
                    return {"id": st["id"]}
            break

    # Search by name match
    for st in cache["types"]:
        name = (st.get("name") or "").lower()
        if desc_lower in name or name in desc_lower:
            return {"id": st["id"]}

    # Fallback: first salary type (usually "Fastlønn")
    if cache["types"]:
        return {"id": cache["types"][0]["id"]}
    return None


@register_handler
class RunPayrollHandler(BaseHandler):
    """Create a salary transaction with payslip for an employee."""

    def get_task_type(self) -> str:
        return "run_payroll"

    @property
    def required_params(self) -> list[str]:
        return ["employee"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today()
        month = params.get("month", today.month)
        year = params.get("year", today.year)
        date = params.get("date", today.isoformat())

        # Step 1: Resolve employee (ensures dateOfBirth, dept, employment)
        emp_ref = resolve_employee(api_client, params["employee"])

        # Step 2: Build salary specifications
        specifications = []
        type_cache: dict[str, list[dict[str, Any]]] = {}

        base_salary = params.get("baseSalary") or params.get("salary")
        if base_salary:
            sal_type = _find_salary_type(api_client, "fastlønn", type_cache)
            spec: dict[str, Any] = {
                "employee": emp_ref,
                "salaryType": sal_type,
                "rate": float(base_salary),
                "count": 1,
                "amount": float(base_salary),
                "year": year,
                "month": month,
            }
            specifications.append(spec)

        # Additional salary lines (bonus, overtime, etc.)
        extras = params.get("extras", params.get("additions", []))
        if isinstance(extras, dict):
            extras = [extras]
        for extra in extras:
            amount = extra.get("amount", 0)
            desc = extra.get("description", "Tillegg")
            sal_type = _find_salary_type(api_client, desc, type_cache)
            spec = {
                "employee": emp_ref,
                "salaryType": sal_type,
                "rate": float(amount),
                "count": 1,
                "amount": float(amount),
                "year": year,
                "month": month,
                "description": desc,
            }
            specifications.append(spec)

        # If bonus is a top-level param
        bonus = params.get("bonus")
        if bonus:
            sal_type = _find_salary_type(api_client, "bonus", type_cache)
            spec = {
                "employee": emp_ref,
                "salaryType": sal_type,
                "rate": float(bonus),
                "count": 1,
                "amount": float(bonus),
                "year": year,
                "month": month,
                "description": params.get("bonusDescription", "Bonus"),
            }
            specifications.append(spec)

        if not specifications:
            return {"error": "no_salary_lines"}

        # Step 3: Create salary transaction
        body: dict[str, Any] = {
            "date": date,
            "year": year,
            "month": month,
            "payslips": [
                {
                    "employee": emp_ref,
                    "date": date,
                    "year": year,
                    "month": month,
                    "specifications": specifications,
                }
            ],
        }

        try:
            result = api_client.post("/salary/transaction", data=body)
            value = result.get("value", {})
            tx_id = value.get("id")
            logger.info("Created salary transaction id=%s", tx_id)
            return {"id": tx_id, "action": "payroll_created"}
        except TripletexApiError as e:
            logger.warning("Salary transaction failed: %s", e)
            return {"error": str(e)}
