"""Tests for bank reconciliation handler."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.handlers.base import get_handler
from tests.conftest import sample_api_response


def _mock_client(
    post_response: dict[str, Any] | None = None,
    put_response: dict[str, Any] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.post.return_value = post_response or sample_api_response(value={"id": 1})
    client.put.return_value = put_response or sample_api_response(value={"id": 1})
    return client


class TestBankRegistration:
    def _ensure_imported(self) -> None:
        import src.handlers  # noqa: F401

    def test_bank_reconciliation_registered(self):
        self._ensure_imported()
        assert get_handler("bank_reconciliation") is not None


class TestBankReconciliation:
    def test_happy_path(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 50}))
        handler = get_handler("bank_reconciliation")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "accountId": 1920,
                "accountingPeriodId": 12,
                "reconciliationDate": "2026-03-31",
            },
        )
        assert result["id"] == 50
        assert result["action"] == "created"
        body = client.post.call_args[1]["data"]
        assert body["account"] == {"id": 1920}
        assert body["accountingPeriod"] == {"id": 12}
        assert body["reconciliationDate"] == "2026-03-31"

    def test_with_adjustments(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 51}))
        handler = get_handler("bank_reconciliation")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "accountId": 1920,
                "adjustments": [
                    {"amount": 100, "description": "Fee adjustment"},
                    {"amount": -50, "description": "Correction"},
                ],
            },
        )
        assert result["id"] == 51
        assert client.put.call_count == 2
        # Verify adjustment endpoint
        first_adj = client.put.call_args_list[0]
        assert "/:adjustment" in first_adj[0][0]

    def test_required_params(self):
        handler = get_handler("bank_reconciliation")
        assert handler is not None
        assert handler.validate_params({}) == []

    def test_minimal_params(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 52}))
        handler = get_handler("bank_reconciliation")
        assert handler is not None
        result = handler.execute(client, {"accountId": 1920})
        assert result["id"] == 52
        body = client.post.call_args[1]["data"]
        assert body["account"] == {"id": 1920}
        assert body["type"] == "MANUAL"
