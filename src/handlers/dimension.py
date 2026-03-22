"""Accounting dimension handler: create dimensions, values, and linked vouchers."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.services.posting_builder import build_posting as _build_posting
from src.services.posting_builder import resolve_account as _resolve_account

logger = logging.getLogger(__name__)


def _find_or_create_dimension(api_client: TripletexClient, name: str) -> tuple[int, int]:
    """Find or create an accounting dimension by name. Returns (id, index)."""
    resp = api_client.get(
        "/ledger/accountingDimensionName",
        fields="id,dimensionName",
    )
    for i, dim in enumerate(resp.get("values", []), start=1):
        if (dim.get("dimensionName") or "").strip().lower() == name.strip().lower():
            return dim["id"], i

    result = api_client.post(
        "/ledger/accountingDimensionName",
        data={"dimensionName": name, "active": True},
    )
    value = result.get("value", {})
    dim_id = value.get("id", 0)
    # Re-fetch to determine the index position
    all_dims = api_client.get("/ledger/accountingDimensionName", fields="id")
    dim_index = 1
    for i, d in enumerate(all_dims.get("values", []), start=1):
        if d.get("id") == dim_id:
            dim_index = i
            break
    logger.info("Created dimension '%s' id=%s index=%s", name, dim_id, dim_index)
    return dim_id, dim_index


def _find_or_create_dimension_value(
    api_client: TripletexClient,
    dim_index: int,
    value_name: str,
) -> int:
    """Find or create an accounting dimension value. Returns value ID."""
    resp = api_client.get(
        "/ledger/accountingDimensionValue/search",
        params={"dimensionIndex": dim_index, "count": 50},
        fields="id,displayName",
    )
    for v in resp.get("values", []):
        if (v.get("displayName") or "").strip().lower() == value_name.strip().lower():
            return v["id"]

    result = api_client.post(
        "/ledger/accountingDimensionValue",
        data={
            "dimensionIndex": dim_index,
            "displayName": value_name,
            "active": True,
            "showInVoucherRegistration": True,
        },
    )
    val_id = result.get("value", {}).get("id", 0)
    logger.info("Created dimension value '%s' id=%s", value_name, val_id)
    return val_id


@register_handler
class CreateDimensionVoucherHandler(BaseHandler):
    """Create accounting dimensions with values, then post a voucher linked to them."""

    tier = 3
    description = "Create dimension with values and linked voucher"

    def get_task_type(self) -> str:
        return "create_dimension_voucher"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today().isoformat()

        # Step 1: Create dimension and values
        dim_name = params.get("dimensionName", "")
        dim_values = params.get("dimensionValues", [])
        linked_value = params.get("linkedValue", "")

        # Also check nested customDimension param
        custom_dim = params.get("customDimension", {})
        if custom_dim:
            dim_name = dim_name or custom_dim.get("name", "")
            dim_values = dim_values or custom_dim.get("values", [])
            linked_value = linked_value or custom_dim.get("linkedValue", "")

        if not dim_name:
            return {"error": "no_dimension_name"}

        dim_id, dim_index = _find_or_create_dimension(api_client, dim_name)

        # Create all dimension values
        value_ids: dict[str, int] = {}
        for val in dim_values:
            val_name = val if isinstance(val, str) else val.get("name", "")
            if val_name:
                val_id = _find_or_create_dimension_value(api_client, dim_index, val_name)
                value_ids[val_name.lower()] = val_id

        # Resolve which value to link to the voucher
        linked_val_id = None
        if linked_value:
            linked_val_id = value_ids.get(linked_value.lower())
            if not linked_val_id:
                linked_val_id = _find_or_create_dimension_value(api_client, dim_index, linked_value)

        # Step 2: Create voucher with dimension if postings provided
        postings = params.get("postings", [])
        # Handle LLM sending voucher info as a sub-object
        voucher_info = params.get("voucher", {})
        if not postings and voucher_info:
            # Extract postings list from voucher sub-object
            postings = voucher_info.get("postings", [])
            # Also check for dimensionValue in individual postings
            for p in postings:
                dv = p.get("dimensionValue", "")
                if dv and not linked_value:
                    linked_value = dv
            # Fallback: single account/amount style
            if not postings:
                acct = voucher_info.get("account", 7300)
                amt = voucher_info.get("amount", 0)
                if amt:
                    postings = [
                        {"account": acct, "amount": amt},
                        {"account": 1920, "amount": -amt},
                    ]
            linked_value = linked_value or voucher_info.get("dimensionValue", "")
            if linked_value and not linked_val_id:
                linked_val_id = value_ids.get(linked_value.lower())
                if not linked_val_id:
                    linked_val_id = _find_or_create_dimension_value(
                        api_client, dim_index, linked_value
                    )
        if not postings:
            return {
                "dimensionId": dim_id,
                "dimensionIndex": dim_index,
                "values": value_ids,
                "action": "dimension_created",
            }

        date_val = params.get("date") or today
        dim_field = f"freeAccountingDimension{dim_index}"

        voucher_postings = []
        for i, p in enumerate(postings):
            posting = _build_posting(api_client, p, row=i + 1)
            # Apply dimension to postings that reference it, or to first posting
            has_dim_value = p.get("dimensionValue")
            if linked_val_id and (has_dim_value or i == 0):
                posting[dim_field] = {"id": linked_val_id}
            voucher_postings.append(posting)

        # Ensure balanced postings: if single posting, add counter-entry
        if len(voucher_postings) == 1:
            amount = voucher_postings[0].get("amountGross", 0)
            bank_acct, _ = _resolve_account(api_client, 1920)
            voucher_postings.append(
                {
                    "row": 2,
                    "account": bank_acct,
                    "amountGross": -amount,
                    "amountGrossCurrency": -amount,
                }
            )

        body: dict[str, Any] = {
            "date": date_val,
            "description": params.get("description") or voucher_info.get("description") or f"Voucher med {dim_name}",
            "postings": voucher_postings,
        }

        try:
            result = api_client.post(
                "/ledger/voucher",
                data=body,
                params={"sendToLedger": "true"},
            )
            voucher = result.get("value", {})
            logger.info("Created voucher id=%s with dimension", voucher.get("id"))
            return {
                "id": voucher.get("id"),
                "dimensionId": dim_id,
                "action": "voucher_with_dimension_created",
            }
        except TripletexApiError as e:
            logger.warning("Voucher creation failed: %s", e)
            return {
                "dimensionId": dim_id,
                "action": "dimension_created_voucher_failed",
                "error": str(e),
            }
