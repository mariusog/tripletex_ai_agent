"""Domain-specific API lookup utilities and infrastructure helpers.

Contains finder functions for invoices, travel expenses, cost categories,
payment types, and bank account setup. These are NOT entity resolution
(find-or-create) — that lives in entity_resolver.py.
"""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.constants import DEFAULT_BANK_ACCOUNT_NUMBER

logger = logging.getLogger(__name__)

_bank_account_set: dict[str, bool] = {}


def ensure_bank_account(api_client: TripletexClient) -> None:
    """Ensure the company has a bank account on ledger account 1920."""
    cache_key = getattr(api_client, "base_url", "") + getattr(api_client, "_token_prefix", "")
    if _bank_account_set.get(cache_key):
        return
    try:
        resp = api_client.get(
            "/ledger/account",
            params={"number": "1920", "count": 1},
            fields="id,bankAccountNumber,version",
        )
        values = resp.get("values", [])
        if not values:
            _bank_account_set[cache_key] = True
            return
        acct = values[0]
        if acct.get("bankAccountNumber"):
            _bank_account_set[cache_key] = True
            return
        api_client.put(
            f"/ledger/account/{acct['id']}",
            data={
                "id": acct["id"],
                "version": acct.get("version", 0),
                "number": 1920,
                "name": "Bankinnskudd",
                "bankAccountNumber": DEFAULT_BANK_ACCOUNT_NUMBER,
            },
        )
        logger.info("Set bank account number on ledger account 1920")
        _bank_account_set[cache_key] = True
    except TripletexApiError as e:
        logger.warning("Failed to set bank account: %s", e)


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


def find_cost_category(
    api_client: TripletexClient,
    description: str,
    cache: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, int] | None:
    """Find a cost category matching the description."""
    if cache is None:
        cache = {}
    if "categories" not in cache:
        resp = api_client.get(
            "/travelExpense/costCategory",
            params={"showOnTravelExpenses": "true", "count": 50},
            fields="id,description",
        )
        cache["categories"] = resp.get("values", [])
    desc_lower = description.lower().strip()
    mapped = COST_CATEGORY_MAP.get(desc_lower)
    for cat in cache["categories"]:
        cat_desc = cat.get("description", "").lower()
        if mapped and cat_desc == mapped.lower():
            return {"id": cat["id"]}
        if desc_lower in cat_desc or cat_desc in desc_lower:
            return {"id": cat["id"]}
    if cache["categories"]:
        return {"id": cache["categories"][0]["id"]}
    return None


def get_travel_payment_type(api_client: TripletexClient) -> dict[str, int] | None:
    """Get the first available travel payment type."""
    resp = api_client.get("/travelExpense/paymentType", params={"count": 1}, fields="id")
    values = resp.get("values", [])
    return {"id": values[0]["id"]} if values else None


def find_travel_expense(api_client: TripletexClient, params: dict[str, Any]) -> int | None:
    """Find travel expense by ID, title, or employee name."""
    if "travelExpenseId" in params:
        return int(params["travelExpenseId"])
    if "id" in params:
        return int(params["id"])
    search_params: dict[str, Any] = {"count": 5}
    if params.get("employeeId"):
        search_params["employeeId"] = int(params["employeeId"])
    resp = api_client.get(
        "/travelExpense",
        params=search_params,
        fields="id,title,employee(id,firstName,lastName)",
    )
    values = resp.get("values", [])
    if not values:
        return None
    title = params.get("title", "")
    if title:
        for v in values:
            if v.get("title", "").strip().lower() == title.strip().lower():
                return v["id"]
    emp = params.get("employee")
    if emp and isinstance(emp, (str, dict)):
        first, last = "", ""
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
    return values[0]["id"] if values else None


def find_invoice_id(api_client: TripletexClient, params: dict[str, Any]) -> int | None:
    """Resolve invoice ID: direct ID avoids a GET call, otherwise search."""
    if "invoiceId" in params:
        return int(params["invoiceId"])
    search_params: dict[str, Any] = {"count": 1}
    if "invoiceNumber" in params:
        search_params["invoiceNumber"] = params["invoiceNumber"]
    elif "customer" in params:
        cust = params["customer"]
        if isinstance(cust, dict):
            if "id" in cust:
                search_params["customerId"] = int(cust["id"])
            else:
                return None
        else:
            try:
                search_params["customerId"] = int(cust)
            except (TypeError, ValueError):
                return None
    else:
        return None
    try:
        resp = api_client.get("/invoice", params=search_params)
        values = resp.get("values", [])
        return values[0].get("id") if values else None
    except TripletexApiError:
        return None
