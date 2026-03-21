"""Unified entity resolver: find-or-create entities across Tripletex API."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient

logger = logging.getLogger(__name__)


def ensure_department_exists(api_client: TripletexClient) -> dict[str, int] | None:
    """Get or create a default department. Returns {"id": N} or None."""
    dept = api_client.get_cached("default_dept", "/department", params={"count": 1}, fields="id")
    if dept.get("values"):
        return {"id": dept["values"][0]["id"]}
    # Fresh sandbox — create a department
    try:
        result = api_client.post("/department", data={"name": "Avdeling", "departmentNumber": "1"})
        dept_id = result.get("value", {}).get("id")
        if dept_id:
            return {"id": dept_id}
    except TripletexApiError:
        pass
    return None


def _ensure_employee_ready(api_client: TripletexClient, emp_id: int) -> None:
    """Ensure an existing employee has dateOfBirth, department, employment."""
    try:
        emp = api_client.get(
            f"/employee/{emp_id}",
            fields="id,dateOfBirth,department(id),version",
        ).get("value", {})
        if not emp:
            return
        needs_update = False
        if not emp.get("dateOfBirth"):
            emp["dateOfBirth"] = "1990-01-01"
            needs_update = True
        if not emp.get("department") or not emp["department"].get("id"):
            dept_ref = ensure_department_exists(api_client)
            if dept_ref:
                emp["department"] = dept_ref
                needs_update = True
        if needs_update:
            api_client.put(f"/employee/{emp_id}", data=emp)
        emp_resp = api_client.get(
            "/employee/employment", params={"employeeId": emp_id, "count": 1}, fields="id"
        )
        if not emp_resp.get("values"):
            start = dt_date.today().replace(day=1).isoformat()
            emp_data: dict[str, Any] = {
                "employee": {"id": emp_id},
                "startDate": start,
                "employmentDetails": [
                    {
                        "date": start,
                        "employmentType": "ORDINARY",
                        "percentageOfFullTimeEquivalent": 100,
                    }
                ],
            }
            # Link to company division if one exists (required for payroll)
            try:
                div_resp = api_client.get_cached(
                    "company_division",
                    "/company/divisions",
                    params={"count": 1},
                    fields="id",
                )
                div_vals = div_resp.get("values", [])
                if div_vals:
                    emp_data["division"] = {"id": div_vals[0]["id"]}
            except TripletexApiError:
                pass
            api_client.post("/employee/employment", data=emp_data)
    except TripletexApiError as e:
        logger.warning("Failed to ensure employee %s ready: %s", emp_id, e)


def _try_direct_id(value: Any) -> dict[str, int] | None:
    """Return {"id": N} if value is already a direct ID reference."""
    if isinstance(value, dict) and "id" in value:
        return {"id": int(value["id"])}
    if isinstance(value, (int, float)):
        return {"id": int(value)}
    if value is not None:
        try:
            return {"id": int(value)}
        except (TypeError, ValueError):
            pass
    return None


def _resolve_customer(api_client: TripletexClient, value: Any) -> dict[str, int]:
    """Resolve customer: create-first with org/email, else search-then-create."""
    if value is None:
        return {"id": 0}
    direct = _try_direct_id(value)
    if direct:
        return direct
    name = str(value) if not isinstance(value, dict) else value.get("name", "")
    if not name:
        return {"id": 0}
    org_nr = value.get("organizationNumber") if isinstance(value, dict) else None
    email = value.get("email") if isinstance(value, dict) else None
    if org_nr or email:
        body: dict[str, Any] = {"name": name}
        if org_nr:
            body["organizationNumber"] = str(org_nr)
        if email:
            body["email"] = email
        try:
            res = api_client.post("/customer", data=body)
            return {"id": res.get("value", {}).get("id")}
        except TripletexApiError:
            pass
    resp = api_client.get("/customer", params={"name": name, "count": 5}, fields="id,name")
    for v in resp.get("values", []):
        if v.get("name", "").strip().lower() == name.strip().lower():
            return {"id": v["id"]}
    res = api_client.post("/customer", data={"name": name})
    return {"id": res.get("value", {}).get("id")}


def _resolve_supplier(api_client: TripletexClient, value: Any) -> dict[str, int] | None:
    """Resolve supplier: always create-first, search as fallback."""
    if value is None:
        return None
    direct = _try_direct_id(value)
    if direct:
        return direct
    name = str(value) if not isinstance(value, dict) else value.get("name", "")
    if not name:
        return None
    org_nr = value.get("organizationNumber") if isinstance(value, dict) else None
    email = value.get("email") if isinstance(value, dict) else None
    sup_body: dict[str, Any] = {"name": name}
    if org_nr:
        sup_body["organizationNumber"] = str(org_nr)
    if email:
        sup_body["email"] = email
        sup_body["invoiceEmail"] = email
    try:
        res = api_client.post("/supplier", data=sup_body)
        return {"id": res.get("value", {}).get("id")}
    except TripletexApiError:
        pass
    try:
        resp = api_client.get("/supplier", params={"name": name, "count": 5}, fields="id,name")
        for v in resp.get("values", []):
            if v.get("name", "").strip().lower() == name.strip().lower():
                return {"id": v["id"]}
    except TripletexApiError:
        pass
    return None


def _resolve_product(
    api_client: TripletexClient,
    value: Any,
    price: Any = None,
) -> dict[str, int]:
    """Resolve product: search first (by number, then name), create if not found."""
    direct = _try_direct_id(value)
    if direct:
        return direct
    name = str(value) if not isinstance(value, dict) else value.get("name", "")
    number = value.get("number") if isinstance(value, dict) else None

    # Search by number first (most precise)
    if number:
        try:
            resp = api_client.get(
                "/product",
                params={"number": str(number), "count": 1},
                fields="id",
            )
            if resp.get("values"):
                return {"id": resp["values"][0]["id"]}
        except TripletexApiError:
            pass

    # Search by name before creating (avoids 422 on name conflict)
    if name:
        try:
            resp = api_client.get("/product", params={"name": name, "count": 5}, fields="id,name")
            for v in resp.get("values", []):
                if v.get("name", "").strip().lower() == name.strip().lower():
                    return {"id": v["id"]}
        except TripletexApiError:
            pass

    # Not found — create
    if name or number:
        prod_body: dict[str, Any] = {"name": name or f"Product {number}"}
        if number:
            prod_body["number"] = int(number)
        if price is not None:
            prod_body["priceExcludingVatCurrency"] = price
        try:
            res = api_client.post("/product", data=prod_body)
            return {"id": res.get("value", {}).get("id")}
        except TripletexApiError:
            # Number conflict — try without number
            try:
                prod_body.pop("number", None)
                res = api_client.post("/product", data=prod_body)
                return {"id": res.get("value", {}).get("id")}
            except TripletexApiError:
                pass
    return {"id": 0}


def _resolve_employee(api_client: TripletexClient, value: Any) -> dict[str, int]:
    """Resolve employee: search first, then create if not found."""
    direct = _try_direct_id(value)
    if direct:
        return direct
    first, last, email = "", "", None
    if isinstance(value, dict):
        first, last = value.get("firstName", ""), value.get("lastName", "")
        email = value.get("email")
    elif isinstance(value, str):
        parts = value.strip().split()
        first = parts[0] if parts else ""
        last = parts[-1] if len(parts) > 1 else ""

    # Search by email first (most precise match)
    if email:
        try:
            resp = api_client.get("/employee", params={"email": email, "count": 1}, fields="id")
            if resp.get("values"):
                _ensure_employee_ready(api_client, resp["values"][0]["id"])
                return {"id": resp["values"][0]["id"]}
        except TripletexApiError:
            pass
    search_params: dict[str, Any] = {"count": 5}
    if first:
        search_params["firstName"] = first
    if last:
        search_params["lastName"] = last
    resp = api_client.get("/employee", params=search_params, fields="id,firstName,lastName")
    for v in resp.get("values", []):
        vf = (v.get("firstName") or "").strip().lower()
        vl = (v.get("lastName") or "").strip().lower()
        if vf == first.strip().lower() and vl == last.strip().lower():
            _ensure_employee_ready(api_client, v["id"])
            return {"id": v["id"]}
    from src.handlers import HANDLER_REGISTRY

    create_params: dict[str, Any] = {
        "firstName": first or "Unknown",
        "lastName": last or "Employee",
    }
    if email:
        create_params["email"] = email
    try:
        result = HANDLER_REGISTRY["create_employee"].execute(api_client, create_params)
        if result.get("id"):
            return {"id": result["id"]}
    except TripletexApiError as e:
        logger.warning("Failed to create employee: %s", e)
    return {"id": 0}


def _resolve_activity(api_client: TripletexClient, value: Any) -> dict[str, int]:
    """Resolve activity: search first, then create if not found."""
    direct = _try_direct_id(value)
    if direct:
        return direct
    name = str(value) if not isinstance(value, dict) else value.get("name", "")
    if not name:
        return {"id": 0}
    # Search first (avoids 422 on name conflict)
    try:
        resp = api_client.get("/activity", params={"name": name, "count": 5}, fields="id,name")
        for v in resp.get("values", []):
            if (v.get("name") or "").strip().lower() == name.strip().lower():
                return {"id": v["id"]}
    except TripletexApiError:
        pass
    # Not found — create
    try:
        res = api_client.post(
            "/activity",
            data={"name": name, "activityType": "PROJECT_GENERAL_ACTIVITY"},
        )
        return {"id": res.get("value", {}).get("id")}
    except TripletexApiError:
        pass
    return {"id": 0}


_RESOLVERS: dict[str, Callable[..., Any]] = {
    "customer": _resolve_customer,
    "supplier": _resolve_supplier,
    "product": _resolve_product,
    "employee": _resolve_employee,
    "activity": _resolve_activity,
}


def resolve(
    api_client: TripletexClient,
    entity_type: str,
    value: Any,
    *,
    extra_create_fields: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Single entry point for ALL entity resolution."""
    resolver = _RESOLVERS.get(entity_type)
    if not resolver:
        raise ValueError(f"Unknown entity type: {entity_type}")
    if entity_type == "product" and extra_create_fields:
        return resolver(api_client, value, price=extra_create_fields.get("price"))
    result = resolver(api_client, value)
    return result if result is not None else {"id": 0}
