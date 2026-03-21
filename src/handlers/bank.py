"""Bank reconciliation handlers via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


@register_handler
class BankReconciliationHandler(BaseHandler):
    """POST /bank/reconciliation, optionally add adjustments.

    Resolves account by number if no ID provided.
    """

    tier = 3
    description = "Perform bank reconciliation"

    def get_task_type(self) -> str:
        return "bank_reconciliation"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        # Resolve account: by ID, or by account number
        account_id = params.get("accountId")
        if not account_id and params.get("accountNumber"):
            resp = api_client.get(
                "/ledger/account",
                params={"number": str(params["accountNumber"]), "count": 1},
                fields="id",
            )
            values = resp.get("values", [])
            if values:
                account_id = values[0]["id"]
        if not account_id and params.get("account"):
            acct = params["account"]
            if isinstance(acct, dict) and "id" in acct:
                account_id = int(acct["id"])
            elif isinstance(acct, (int, str)):
                try:
                    acct_num = int(acct)
                    resp = api_client.get(
                        "/ledger/account",
                        params={"number": str(acct_num), "count": 1},
                        fields="id",
                    )
                    values = resp.get("values", [])
                    if values:
                        account_id = values[0]["id"]
                except (TypeError, ValueError):
                    pass
        if not account_id:
            # Default to account 1920 (bank)
            resp = api_client.get(
                "/ledger/account",
                params={"number": "1920", "count": 1},
                fields="id",
            )
            values = resp.get("values", [])
            account_id = values[0]["id"] if values else 0

        from datetime import date as dt_date

        body: dict[str, Any] = {"account": {"id": int(account_id)}}

        if "accountingPeriodId" in params:
            body["accountingPeriod"] = {"id": int(params["accountingPeriodId"])}
        else:
            # Look up the current accounting period
            try:
                today = dt_date.today().isoformat()
                period_resp = api_client.get(
                    "/ledger/accountingPeriod",
                    params={"dateFrom": today, "dateTo": today, "count": 1},
                    fields="id",
                )
                period_vals = period_resp.get("values", [])
                if period_vals:
                    body["accountingPeriod"] = {"id": period_vals[0]["id"]}
            except Exception:
                logger.warning("Could not find accounting period")

        if "reconciliationDate" in params:
            date_val = self.validate_date(params["reconciliationDate"], "reconciliationDate")
            if date_val:
                body["reconciliationDate"] = date_val

        # type is required — default to MANUAL_RECONCILIATION
        body["type"] = params.get("type", "MANUAL_RECONCILIATION")

        if "isClosed" in params and params["isClosed"] is not None:
            body["isClosed"] = params["isClosed"]

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
