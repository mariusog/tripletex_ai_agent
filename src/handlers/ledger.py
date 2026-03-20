"""Ledger/voucher handlers: create and reverse vouchers via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


def _resolve_supplier(api_client: TripletexClient, supplier: Any) -> dict[str, int] | None:
    """Resolve supplier to {"id": N}. Creates if not found."""
    if supplier is None:
        return None
    if isinstance(supplier, dict) and "id" in supplier:
        return {"id": int(supplier["id"])}
    if isinstance(supplier, (int, float)):
        return {"id": int(supplier)}
    name = str(supplier) if not isinstance(supplier, dict) else supplier.get("name", "")
    org_nr = supplier.get("organizationNumber") if isinstance(supplier, dict) else None
    if not name:
        return None
    # Search by name (verify exact match — API search is fuzzy)
    try:
        resp = api_client.get("/supplier", params={"name": name, "count": 5}, fields="id,name")
        values = resp.get("values", [])
        logger.info("Supplier search for '%s' returned %d results", name, len(values))
        for v in values:
            if v.get("name", "").strip().lower() == name.strip().lower():
                logger.info("Found exact supplier match: id=%s name='%s'", v["id"], v.get("name"))
                return {"id": v["id"]}
    except TripletexApiError:
        pass  # Search failed, create instead
    # Create
    sup_body: dict[str, Any] = {"name": name}
    if org_nr:
        sup_body["organizationNumber"] = str(org_nr)
    result = api_client.post("/supplier", data=sup_body)
    sup_id = result.get("value", {}).get("id")
    logger.info("Auto-created supplier '%s' id=%s", name, sup_id)
    return {"id": sup_id}


def _resolve_account(
    api_client: TripletexClient, account: Any
) -> tuple[dict[str, int], dict[str, int] | None]:
    """Resolve account number to ({"id": N}, vatType ref or None)."""
    if isinstance(account, dict) and "id" in account:
        return {"id": int(account["id"])}, None
    try:
        number = int(account)
    except (TypeError, ValueError):
        return {"id": 0}, None
    resp = api_client.get_cached(
        f"account_{number}",
        "/ledger/account",
        params={"number": str(number), "count": 1},
        fields="id,vatType(id)",
    )
    values = resp.get("values", [])
    if values:
        vat = values[0].get("vatType")
        vat_ref = {"id": vat["id"]} if vat and vat.get("id") else None
        return {"id": values[0]["id"]}, vat_ref
    logger.warning("Account %d not found", number)
    return {"id": 0}, None


def _create_custom_dimension(
    api_client: TripletexClient, dim_params: dict[str, Any]
) -> dict[str, int] | None:
    """Create a custom accounting dimension with values. Returns the linked value ref."""
    dim_name = dim_params.get("name", "")
    values = dim_params.get("values", [])
    linked_value = dim_params.get("linkedValue", "")

    if not dim_name:
        return None

    # Create the dimension name
    try:
        dim_result = api_client.post(
            "/ledger/accountingDimensionName",
            data={"dimensionName": dim_name, "active": True},
        )
        dim_index = dim_result.get("value", {}).get("dimensionIndex")
        logger.info("Created dimension '%s' index=%s", dim_name, dim_index)
    except TripletexApiError:
        logger.warning("Failed to create dimension '%s', may already exist", dim_name)
        dim_index = None

    # Create dimension values
    linked_ref = None
    for val in values:
        val_name = val if isinstance(val, str) else val.get("name", "")
        if not val_name:
            continue
        try:
            val_body: dict[str, Any] = {
                "displayName": val_name,
                "number": val_name[:10],
                "active": True,
                "showInVoucherRegistration": True,
            }
            if dim_index is not None:
                val_body["dimensionIndex"] = dim_index
            val_result = api_client.post("/ledger/accountingDimensionValue", data=val_body)
            val_id = val_result.get("value", {}).get("id")
            logger.info("Created dimension value '%s' id=%s", val_name, val_id)
            if val_name == linked_value and val_id:
                linked_ref = {"id": val_id}
        except TripletexApiError as e:
            logger.warning("Failed to create dimension value '%s': %s", val_name, e)

    return linked_ref


def _build_posting(
    api_client: TripletexClient,
    posting: dict[str, Any],
    row: int = 0,
    supplier: dict[str, int] | None = None,
    dimension_ref: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a single voucher posting payload.

    Handles multiple LLM output formats:
    - {account: 5000, debit: 10000} — single account with debit/credit
    - {debitAccount: 5000, creditAccount: 2930, amountGross: 10000} — split accounts
    - {account: 5000, amountGross: 10000} — direct amount
    """
    result: dict[str, Any] = {"row": row}
    vat_ref = None

    # Resolve account — LLM may use "account", "debitAccount", or "creditAccount"
    account = posting.get("account") or posting.get("debitAccount") or posting.get("creditAccount")
    if account:
        acct_ref, vat_ref = _resolve_account(api_client, account)
        result["account"] = acct_ref

    for field in ("amountCurrency", "amount", "description"):
        if field in posting and posting[field] is not None:
            result[field] = posting[field]

    # Handle debit/credit amounts
    debit = posting.get("debit", 0) or 0
    credit = posting.get("credit", 0) or 0
    # If LLM used debitAccount/creditAccount split format, the amount is positive
    # for debit account and we need to generate a matching credit posting separately
    if posting.get("debitAccount") and posting.get("creditAccount"):
        # This posting represents a debit; the caller should also generate a credit
        amount = abs(posting.get("amountGross", 0))
    elif debit and not credit:
        amount = abs(debit)
    elif credit and not debit:
        amount = -abs(credit)
    elif "amountGross" in posting and posting["amountGross"] is not None:
        amount = posting["amountGross"]
    else:
        amount = 0
    result["amountGross"] = amount
    result["amountGrossCurrency"] = amount
    # Set VAT type from account default if not explicitly provided
    if "vatType" in posting:
        result["vatType"] = BaseHandler.ensure_ref(posting["vatType"], "vatType")
    elif vat_ref:
        result["vatType"] = vat_ref
    # Add supplier ref if provided (required for AP/supplier invoice postings)
    if supplier:
        result["supplier"] = supplier
    # Add custom dimension ref if provided
    if dimension_ref:
        result["freeAccountingDimension1"] = dimension_ref
    return {k: v for k, v in result.items() if v is not None}


@register_handler
class CreateVoucherHandler(BaseHandler):
    """POST /ledger/voucher with debit/credit postings. 1 API call."""

    def get_task_type(self) -> str:
        return "create_voucher"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import date as dt_date

        date_val = self.validate_date(params.get("date"), "date")
        if not date_val:
            date_val = dt_date.today().isoformat()

        body: dict[str, Any] = {"date": date_val}

        if params.get("description"):
            body["description"] = params["description"]
        # number and tempNumber are readOnly (system-generated)

        if "voucherType" in params:
            body["voucherType"] = {"id": int(params["voucherType"])}

        # Create custom accounting dimensions if requested
        dim_value_ref = None
        if params.get("customDimension"):
            dim_value_ref = _create_custom_dimension(api_client, params["customDimension"])

        # Resolve supplier if present (needed for supplier invoice vouchers)
        supplier_ref = _resolve_supplier(api_client, params.get("supplier"))

        # Build postings — resolve account numbers to IDs
        # Handle split debit/credit format: expand into two postings
        raw_postings = params.get("postings", [])
        expanded: list[dict[str, Any]] = []
        for p in raw_postings:
            if p.get("debitAccount") and p.get("creditAccount"):
                amt = abs(p.get("amountGross", p.get("amount", 0)))
                expanded.append(
                    {
                        "account": p["debitAccount"],
                        "amountGross": amt,
                        "description": p.get("description", ""),
                    }
                )
                expanded.append(
                    {
                        "account": p["creditAccount"],
                        "amountGross": -amt,
                        "description": p.get("description", ""),
                    }
                )
            else:
                expanded.append(p)

        if expanded:
            body["postings"] = [
                _build_posting(
                    api_client,
                    p,
                    row=i + 1,
                    supplier=supplier_ref,
                    dimension_ref=dim_value_ref,
                )
                for i, p in enumerate(expanded)
            ]

        body = self.strip_none_values(body)
        result = api_client.post(
            "/ledger/voucher",
            data=body,
            params={"sendToLedger": "true"},
        )
        value = result.get("value", {})
        logger.info("Created voucher id=%s", value.get("id"))
        return {"id": value.get("id"), "action": "created"}


@register_handler
class DeleteVoucherHandler(BaseHandler):
    """GET /ledger/voucher (search) then DELETE /ledger/voucher/{id}."""

    def get_task_type(self) -> str:
        return "delete_voucher"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        voucher_id = params.get("voucherId") or params.get("id")
        if not voucher_id:
            # Search for voucher — dateFrom/dateTo are required by API
            from datetime import date as dt_date

            today = dt_date.today().isoformat()
            search_params: dict[str, Any] = {
                "count": 10,
                "dateFrom": params.get("dateFrom", "2020-01-01"),
                "dateTo": params.get("dateTo", today),
            }
            if params.get("date"):
                date_val = self.validate_date(params["date"], "date")
                if date_val:
                    search_params["dateFrom"] = date_val
                    search_params["dateTo"] = date_val
            if params.get("number"):
                search_params["number"] = str(params["number"])
            resp = api_client.get(
                "/ledger/voucher", params=search_params, fields="id,number,description"
            )
            values = resp.get("values", [])
            if not values:
                logger.warning("No vouchers found to delete")
                return {"error": "not_found"}
            # Match by description if given
            desc = params.get("description", "")
            if desc:
                for v in values:
                    if desc.lower() in (v.get("description") or "").lower():
                        voucher_id = v["id"]
                        break
            if not voucher_id:
                voucher_id = values[0]["id"]

        api_client.delete(f"/ledger/voucher/{int(voucher_id)}")
        logger.info("Deleted voucher id=%s", voucher_id)
        return {"id": int(voucher_id), "action": "deleted"}


@register_handler
class ReverseVoucherHandler(BaseHandler):
    """POST /ledger/voucher/{id}/:reverse. 1 API call."""

    def get_task_type(self) -> str:
        return "reverse_voucher"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        # If no voucherId, fall back to register_payment with reversal
        if "voucherId" not in params and params.get("customer"):
            from src.handlers.invoice import RegisterPaymentHandler

            pay_params = dict(params)
            amount = params.get("amount", 0)
            pay_params["amount"] = -abs(amount) if amount > 0 else amount
            pay_params["reversal"] = True
            handler = RegisterPaymentHandler()
            return handler.execute(api_client, pay_params)

        from datetime import date as dt_date

        voucher_id = int(params.get("voucherId", 0))
        if not voucher_id:
            return {"error": "no_voucher_id"}
        # Spec: PUT /ledger/voucher/{id}/:reverse with date as required query param
        date_val = self.validate_date(params.get("date"), "date") or dt_date.today().isoformat()
        api_client.put(
            f"/ledger/voucher/{voucher_id}/:reverse",
            params={"date": date_val},
        )
        logger.info("Reversed voucher id=%s", voucher_id)
        return {"id": voucher_id, "action": "reversed"}
