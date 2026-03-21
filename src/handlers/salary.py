"""Salary/payroll handler: run payroll via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, ParamSpec, register_handler
from src.handlers.entity_resolver import resolve

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

    tier = 3
    description = "Run payroll for an employee"
    param_schema = {
        "employee": ParamSpec(description="Employee name or {firstName, lastName, email}"),
        "baseSalary": ParamSpec(required=False, type="number", description="Base monthly salary"),
        "bonus": ParamSpec(required=False, type="number"),
        "bonusDescription": ParamSpec(required=False),
        "month": ParamSpec(required=False, type="number"),
        "year": ParamSpec(required=False, type="number"),
        "extras": ParamSpec(required=False, type="list", description="Additional salary lines"),
    }

    def get_task_type(self) -> str:
        return "run_payroll"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today()
        month = params.get("month", today.month)
        year = params.get("year", today.year)
        date = params.get("date", today.isoformat())

        # Step 1: Resolve employee (ensures dateOfBirth, dept, employment)
        emp_ref = resolve(api_client, "employee", params["employee"])

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
            logger.warning("Salary transaction failed: %s, falling back to voucher", e)
            return self._fallback_voucher(api_client, params, date)

    @staticmethod
    def _fallback_voucher(
        api_client: TripletexClient, params: dict[str, Any], date: str
    ) -> dict[str, Any]:
        """Fall back to manual voucher when salary API is unavailable."""
        from src.handlers.base import HANDLER_REGISTRY

        total = 0.0
        base = params.get("baseSalary") or params.get("salary") or 0
        bonus = params.get("bonus") or 0
        total = float(base) + float(bonus)

        # Add extras
        for extra in params.get("extras", []):
            total += float(extra.get("amount", 0))

        if not total:
            return {"error": "no_salary_amount"}

        voucher_params: dict[str, Any] = {
            "description": "Lønn / Payroll",
            "date": date,
            "postings": [
                {
                    "debitAccount": "5000",
                    "creditAccount": "2900",
                    "amount": total,
                    "description": "Lønn / Payroll",
                }
            ],
        }

        handler = HANDLER_REGISTRY.get("create_voucher")
        if handler:
            result = handler.execute(api_client, voucher_params)
            logger.info("Payroll fallback voucher id=%s", result.get("id"))
            return {
                "id": result.get("id"),
                "action": "payroll_voucher_fallback",
            }
        return {"error": "no_voucher_handler"}
