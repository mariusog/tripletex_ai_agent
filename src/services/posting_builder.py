"""Voucher posting builder: account resolution, amount handling, VAT merge.

Single source of truth for constructing Tripletex voucher posting payloads.
Used by ledger.py, bank.py, reporting.py, dimension.py.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler

logger = logging.getLogger(__name__)


# Common Norwegian account numbers → names (for auto-creation)
_ACCOUNT_NUMBER_NAMES: dict[int, str] = {
    1000: "Kontanter",
    1009: "Avskrivning forskning og utvikling",
    1020: "Patenter",
    1029: "Avskrivning patenter",
    1030: "Utsatt skattefordel",
    1039: "Avskrivning utsatt skattefordel",
    1050: "Goodwill",
    1100: "Bygninger",
    1109: "Avskrivning bygninger",
    1200: "Maskiner og anlegg",
    1209: "Avskrivning maskiner og anlegg",
    1210: "Biler",
    1219: "Avskrivning biler",
    1240: "Inventar",
    1249: "Avskrivning inventar",
    1250: "Programvare",
    1259: "Avskrivning programvare",
    1280: "Kontormaskiner",
    1289: "Avskrivning kontormaskiner",
    1500: "Kundefordringer",
    1700: "Forskuddsbetalt leiekostnad",
    1720: "Forskuddsbetalt forsikring",
    1920: "Bankinnskudd",
    2400: "Leverandørgjeld",
    2700: "Utgående merverdiavgift",
    2710: "Inngående merverdiavgift",
    2900: "Påløpt lønn",
    2920: "Betalbar skatt",
    3000: "Salgsinntekt",
    3900: "Annen driftsrelatert inntekt",
    5000: "Lønn til ansatte",
    6000: "Avskrivning",
    6010: "Avskrivning bygninger og annen fast eiendom",
    6020: "Avskrivning transportmidler",
    6030: "Avskrivning maskiner",
    6040: "Avskrivning inventar",
    6050: "Avskrivning programvare",
    6300: "Leie lokale",
    6340: "Lys, varme",
    6500: "Verktøy og inventar",
    6540: "Inventar",
    6800: "Kontorrekvisita",
    6860: "Møter, kurs",
    7000: "Reisekostnad",
    7140: "Reisekostnad, ikke oppgavepliktig",
    7150: "Diettkostnad",
    7300: "Salgskostnad",
    7350: "Representasjon",
    8060: "Agio (valutagevinst)",
    8160: "Disagio (valutatap)",
    8700: "Skattekostnad",
}

# Norwegian accounting term → account number range mapping
_ACCOUNT_NAME_RANGES: dict[str, tuple[int, int]] = {
    "kostkonto": (6000, 6999),
    "kostnadskonto": (6000, 6999),
    "driftskostnad": (6000, 6999),
    "expense": (6000, 6999),
    "lønn": (5000, 5099),
    "salary": (5000, 5099),
    "avskrivning": (6010, 6020),
    "depreciation": (6010, 6020),
    "inntekt": (3000, 3999),
    "revenue": (3000, 3999),
}


def _resolve_account_by_name(
    api_client: TripletexClient, name: str
) -> tuple[dict[str, int], dict[str, int] | None]:
    """Resolve a non-numeric account identifier by name or keyword."""
    name_lower = name.strip().lower()
    # Try keyword mapping first
    for keyword, (range_start, range_end) in _ACCOUNT_NAME_RANGES.items():
        if keyword in name_lower:
            try:
                all_resp = api_client.get(
                    "/ledger/account",
                    params={"count": 1000},
                    fields="id,number,vatType(id)",
                )
                for acct in all_resp.get("values", []):
                    acct_num = acct.get("number", 0)
                    if range_start <= acct_num <= range_end:
                        vat = acct.get("vatType")
                        vat_ref = {"id": vat["id"]} if vat and vat.get("id") else None
                        logger.info("Resolved account name '%s' to %d", name, acct_num)
                        return {"id": acct["id"]}, vat_ref
            except TripletexApiError:
                pass
            break
    logger.warning("Could not resolve account name '%s'", name)
    return {"id": 0}, None


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
        # Non-numeric account name — try to resolve by name search
        if isinstance(account, str) and account.strip():
            return _resolve_account_by_name(api_client, account)
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
    # Account not found — try fresh GET (cache may be stale from earlier step)
    try:
        fresh = api_client.get(
            "/ledger/account",
            params={"number": str(number), "count": 1},
            fields="id,number,vatType(id)",
        )
        fvals = fresh.get("values", [])
        if fvals:
            vat = fvals[0].get("vatType")
            vat_ref = {"id": vat["id"]} if vat and vat.get("id") else None
            return {"id": fvals[0]["id"]}, vat_ref
    except TripletexApiError:
        pass
    # Still not found — create it
    try:
        name = _ACCOUNT_NUMBER_NAMES.get(number, f"Konto {number}")
        create_resp = api_client.post(
            "/ledger/account",
            data={"number": number, "name": name},
        )
        created = create_resp.get("value", {})
        if created.get("id"):
            vat = created.get("vatType")
            vat_ref = {"id": vat["id"]} if vat and vat.get("id") else None
            logger.info("Created missing account %d (%s)", number, name)
            return {"id": created["id"]}, vat_ref
    except TripletexApiError as e:
        # Creation failed — one more fresh GET attempt
        try:
            fresh2 = api_client.get(
                "/ledger/account",
                params={"number": str(number), "count": 1},
                fields="id,number,vatType(id)",
            )
            fvals2 = fresh2.get("values", [])
            if fvals2:
                vat = fvals2[0].get("vatType")
                vat_ref = {"id": vat["id"]} if vat and vat.get("id") else None
                return {"id": fvals2[0]["id"]}, vat_ref
        except TripletexApiError:
            pass
        logger.warning("Could not create account %d: %s", number, e)
    logger.warning("Account %d not found and could not be created", number)
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
    # Department ref on posting — only for expense/cost accounts (4000+)
    dept = posting.get("department")
    acct_num_for_dept = 0
    if acct:
        with contextlib.suppress(TypeError, ValueError):
            acct_num_for_dept = int(acct)
    if dept and acct_num_for_dept >= 4000:
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
