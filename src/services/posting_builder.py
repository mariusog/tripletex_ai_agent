"""Voucher posting builder: account resolution, amount handling, VAT merge.

Single source of truth for constructing Tripletex voucher posting payloads.
Used by ledger.py, bank.py, reporting.py, dimension.py.
"""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler

logger = logging.getLogger(__name__)


def resolve_account(
    api_client: TripletexClient, account: Any
) -> tuple[dict[str, int], dict[str, int] | None]:
    """Resolve account number to ({"id": N}, vatType ref or None).

    If exact number not found, searches by number range to find the closest.
    """
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
        fields="id,number,vatType(id)",
    )
    values = resp.get("values", [])
    if values:
        vat = values[0].get("vatType")
        vat_ref = {"id": vat["id"]} if vat and vat.get("id") else None
        return {"id": values[0]["id"]}, vat_ref
    # Account not found — search by wider ranges
    # First try exact 100-range, then 1000-range
    for range_start, range_end in [
        ((number // 100) * 100, (number // 100) * 100 + 99),
        ((number // 1000) * 1000, (number // 1000) * 1000 + 999),
    ]:
        try:
            range_resp = api_client.get(
                "/ledger/account",
                params={
                    "numberFrom": str(range_start),
                    "numberTo": str(range_end),
                    "count": 1,
                },
                fields="id,number,vatType(id)",
            )
            range_vals = range_resp.get("values", [])
            if range_vals:
                found_num = range_vals[0].get("number", 0)
                if range_start <= found_num <= range_end:
                    vat = range_vals[0].get("vatType")
                    vat_ref = {"id": vat["id"]} if vat and vat.get("id") else None
                    logger.info(
                        "Account %d not found, using %d instead",
                        number,
                        found_num,
                    )
                    return {"id": range_vals[0]["id"]}, vat_ref
        except TripletexApiError:
            pass
    logger.warning("Account %d not found in range %d-%d", number, range_start, range_end)
    return {"id": 0}, None


def build_posting(
    api_client: TripletexClient,
    posting: dict[str, Any],
    row: int = 0,
    supplier: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a single voucher posting payload."""
    result: dict[str, Any] = {"row": row}
    vat_ref = None
    acct = posting.get("account") or posting.get("debitAccount") or posting.get("creditAccount")
    if acct:
        acct_ref, vat_ref = resolve_account(api_client, acct)
        result["account"] = acct_ref
    for field in ("amountCurrency", "amount", "description"):
        if field in posting and posting[field] is not None:
            result[field] = posting[field]
    # Handle debit/credit amounts (booleans already normalized by param_normalizer)
    debit = posting.get("debit", 0) or 0
    credit = posting.get("credit", 0) or 0
    if debit and not credit:
        amount = abs(debit)
    elif credit and not debit:
        amount = -abs(credit)
    elif "amountGross" in posting and posting["amountGross"] is not None:
        amount = posting["amountGross"]
    elif "amount" in posting and posting["amount"] is not None:
        amount = posting["amount"]
    else:
        amount = 0
    result["amountGross"] = amount
    result["amountGrossCurrency"] = amount
    # Set VAT type: use account's default (respects locked accounts)
    if "vatType" in posting:
        vt_val = posting["vatType"]
        # Percentage string ("25%") or small int (25) → use account default
        if isinstance(vt_val, str) and "%" in vt_val:
            if vat_ref:
                result["vatType"] = vat_ref
        elif isinstance(vt_val, (int, float)) and vt_val in (0, 6, 12, 15, 25):
            # Looks like a percentage, not an ID — use account default
            if vat_ref:
                result["vatType"] = vat_ref
        else:
            result["vatType"] = BaseHandler.ensure_ref(vt_val, "vatType")
    elif vat_ref:
        result["vatType"] = vat_ref
    if supplier:
        result["supplier"] = supplier
    # Department ref on posting (resolve name to ID if string)
    dept = posting.get("department")
    if dept:
        if isinstance(dept, dict) and "id" in dept:
            result["department"] = dept
        elif isinstance(dept, str):
            try:
                dept_resp = api_client.get(
                    "/department", params={"name": dept, "count": 5}, fields="id,name"
                )
                for dv in dept_resp.get("values", []):
                    if dv.get("name", "").strip().lower() == dept.strip().lower():
                        result["department"] = {"id": dv["id"]}
                        break
            except Exception:
                logger.warning("Could not resolve department '%s'", dept)
    return {k: v for k, v in result.items() if v is not None}


def merge_vat_postings(
    postings: list[dict[str, Any]], vat_rate: Any = None
) -> list[dict[str, Any]]:
    """Merge manual VAT split into gross posting with vatType.

    If LLM sent: debit 6340 (net), debit 2710 (VAT), credit 2400 (gross)
    Merge to: debit 6340 (gross, with vatRate), credit 2400 (gross)
    """
    if len(postings) < 3:
        return postings

    vat_idx = None
    for i, p in enumerate(postings):
        acct = p.get("account") or p.get("debitAccount") or ""
        try:
            acct_num = int(acct)
        except (TypeError, ValueError):
            continue
        if 2710 <= acct_num <= 2719:
            vat_idx = i
            break

    if vat_idx is None:
        return postings

    vat_posting = postings[vat_idx]
    vat_amount = (
        vat_posting.get("debit") or vat_posting.get("debitAmount") or vat_posting.get("amount") or 0
    )

    expense_idx = None
    for i, p in enumerate(postings):
        if i == vat_idx:
            continue
        acct = p.get("account") or p.get("debitAccount") or ""
        try:
            acct_num = int(acct)
        except (TypeError, ValueError):
            continue
        if acct_num not in range(2400, 2500) and acct_num not in range(2710, 2720):
            debit = p.get("debit") or p.get("debitAmount") or p.get("amount", 0)
            if debit and debit > 0:
                expense_idx = i
                break

    if expense_idx is None:
        return postings

    merged = list(postings)
    expense = dict(merged[expense_idx])
    net = expense.get("debit") or expense.get("debitAmount") or expense.get("amount") or 0
    gross = net + vat_amount
    expense["debit"] = gross
    expense["debitAmount"] = gross
    if "amount" in expense:
        expense["amount"] = gross
    expense["vatRate"] = vat_rate or 25
    merged[expense_idx] = expense
    merged.pop(vat_idx)
    logger.info("Merged VAT posting: net=%s + vat=%s = gross=%s", net, vat_amount, gross)
    return merged
