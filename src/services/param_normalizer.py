"""Normalize LLM-extracted parameters before handler execution.

The LLM produces varied output formats for the same semantic concept.
This module normalizes them into the format handlers expect, avoiding
422 errors from the Tripletex API.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def normalize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM output params to handler-expected formats.

    Handles: address strings, boolean debit/credit, percentage vatType,
    nested customer/employee/supplier references.
    """
    result = dict(params)

    # Normalize address fields (string → object)
    for addr_field in ("postalAddress", "physicalAddress", "deliveryAddress"):
        if addr_field in result and isinstance(result[addr_field], str):
            result[addr_field] = {"addressLine1": result[addr_field]}

    # Normalize flat "address" → postalAddress
    if "address" in result and "postalAddress" not in result:
        addr = result.pop("address")
        if isinstance(addr, str):
            result["postalAddress"] = {"addressLine1": addr}
        elif isinstance(addr, dict):
            result["postalAddress"] = addr

    # Normalize customer: string → {"name": string}
    if "customer" in result and isinstance(result["customer"], str):
        name = result["customer"]
        org = result.pop("organizationNumber", None)
        cust: dict[str, Any] = {"name": name}
        if org:
            cust["organizationNumber"] = str(org)
        result["customer"] = cust

    # Normalize employee: string → {"firstName": ..., "lastName": ...}
    if "employee" in result and isinstance(result["employee"], str):
        parts = result["employee"].strip().split()
        if len(parts) >= 2:
            result["employee"] = {"firstName": parts[0], "lastName": " ".join(parts[1:])}

    # Normalize supplier: string → {"name": string}
    if "supplier" in result and isinstance(result["supplier"], str):
        result["supplier"] = {"name": result["supplier"]}

    # Normalize postings
    if "postings" in result and isinstance(result["postings"], list):
        result["postings"] = [_normalize_posting(p) for p in result["postings"]]

    # Normalize debitAmount/creditAmount aliases at top level
    for alias_from, alias_to in [
        ("debitAmount", "debit"),
        ("creditAmount", "credit"),
    ]:
        if alias_from in result and alias_to not in result:
            result[alias_to] = result.pop(alias_from)

    # Strip context pollution from multi-step (invoiceId from previous step)
    if "invoiceId" in result and result.get("invoiceId") == result.get("id"):
        result.pop("invoiceId", None)

    # Strip placeholder customer names the LLM generates
    if "customer" in result:
        cust = result["customer"]
        name = cust.get("name", "") if isinstance(cust, dict) else str(cust)
        if name and ("<" in name or "UNKNOWN" in name.upper() or "OVERDUE" in name.upper()):
            result.pop("customer", None)

    return result


def _normalize_posting(posting: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single voucher posting from LLM output."""
    p = dict(posting)

    # Nested debit/credit objects → flatten
    # e.g. {"debit": {"account": 1500, "amount": 100}} → {"account": 1500, "debit": 100}
    for side in ("debit", "credit"):
        if isinstance(p.get(side), dict):
            nested = p.pop(side)
            if "account" in nested and "account" not in p:
                p["account"] = nested["account"]
            amt = nested.get("amount") or nested.get("amountGross") or 0
            p[side] = abs(amt)
            if "description" in nested and "description" not in p:
                p["description"] = nested["description"]

    # Boolean debit/credit → use amount field
    if isinstance(p.get("debit"), bool):
        is_debit = p.pop("debit")
        raw = p.get("amount") or p.get("amountGross") or 0
        if is_debit:
            p["debit"] = abs(raw)
        else:
            p["credit"] = abs(raw)
        p.pop("amount", None)

    if isinstance(p.get("credit"), bool):
        is_credit = p.pop("credit")
        raw = p.get("amount") or p.get("amountGross") or 0
        if is_credit:
            p["credit"] = abs(raw)
        else:
            p["debit"] = abs(raw)
        p.pop("amount", None)

    # Normalize debitAmount/creditAmount aliases
    if "debitAmount" in p and "debit" not in p:
        p["debit"] = p.pop("debitAmount")
    if "creditAmount" in p and "credit" not in p:
        p["credit"] = p.pop("creditAmount")

    # Percentage vatType strings → drop (let account default handle it)
    if "vatType" in p:
        vt = p["vatType"]
        if isinstance(vt, str) and "%" in vt:
            p.pop("vatType")

    return p
