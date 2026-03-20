"""Bank reconciliation handlers via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


def _resolve_account_id(api_client: TripletexClient, params: dict[str, Any]) -> int:
    """Resolve account ID from accountId, account number, or account name."""
    if "accountId" in params:
        return int(params["accountId"])

    account = params.get("account") or params.get("accountNumber") or "1920"
    try:
        number = int(account)
    except (TypeError, ValueError):
        number = 1920

    resp = api_client.get_cached(
        f"account_{number}",
        "/ledger/account",
        params={"number": str(number), "count": 1},
        fields="id",
    )
    values = resp.get("values", [])
    if values:
        return values[0]["id"]

    logger.warning("Account %s not found, defaulting to searching all", number)
    return 0


@register_handler
class BankReconciliationHandler(BaseHandler):
    """POST /bank/reconciliation, optionally add adjustments.

    Resolves account number to ID if needed. Handles both direct
    accountId and account number from prompts.
    """

    def get_task_type(self) -> str:
        return "bank_reconciliation"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        account_id = _resolve_account_id(api_client, params)
        if not account_id:
            return {"error": "account_not_found"}

        body: dict[str, Any] = {"account": {"id": account_id}}

        if "accountingPeriodId" in params:
            body["accountingPeriod"] = {"id": int(params["accountingPeriodId"])}

        if "reconciliationDate" in params:
            date_val = self.validate_date(params["reconciliationDate"], "reconciliationDate")
            if date_val:
                body["reconciliationDate"] = date_val

        for field in ("type", "isClosed"):
            if field in params and params[field] is not None:
                body[field] = params[field]

        body = self.strip_none_values(body)
        result = api_client.post("/bank/reconciliation", data=body)
        value = result.get("value", {})
        recon_id = value.get("id")
        logger.info("Created bank reconciliation id=%s", recon_id)

        for adj in params.get("adjustments", []):
            self._add_adjustment(api_client, recon_id, adj)

        return {"id": recon_id, "action": "created"}

    def _add_adjustment(
        self, api_client: TripletexClient, recon_id: int, adj: dict[str, Any]
    ) -> None:
        adj_body: dict[str, Any] = {}
        for field in ("amount", "description", "paymentType"):
            if field in adj and adj[field] is not None:
                adj_body[field] = adj[field]
        if "date" in adj:
            date_val = self.validate_date(adj["date"], "adjustment.date")
            if date_val:
                adj_body["date"] = date_val
        if adj_body:
            api_client.put(f"/bank/reconciliation/{recon_id}/:adjustment", data=adj_body)
            logger.info("Added adjustment to reconciliation id=%s", recon_id)
