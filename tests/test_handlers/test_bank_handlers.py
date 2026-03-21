"""Tests for bank reconciliation handler."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.handlers.base import get_handler
from tests.conftest import sample_api_response


def _mock_client(
    post_response: dict[str, Any] | None = None,
    get_response: dict[str, Any] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.base_url = "https://test.tripletex.no/v2"
    client.post.return_value = post_response or sample_api_response(value={"id": 1})
    client.put.return_value = sample_api_response(value={"id": 1})
    client.get.return_value = get_response or sample_api_response(values=[{"id": 100}])
    client.get_cached.return_value = sample_api_response(values=[{"id": 100}])
    return client


class TestBankRegistration:
    def _ensure_imported(self) -> None:
        import src.handlers  # noqa: F401

    def test_bank_reconciliation_registered(self):
        self._ensure_imported()
        assert get_handler("bank_reconciliation") is not None


class TestBankReconciliation:
    def test_basic_reconciliation(self):
        """Fallback path: no customer/supplier data, creates simple reconciliation."""
        client = _mock_client(post_response=sample_api_response(value={"id": 52}))
        handler = get_handler("bank_reconciliation")
        assert handler is not None
        result = handler.execute(client, {"accountNumber": "1920"})
        assert result["id"] == 52
        assert result["action"] == "created"

    def test_required_params(self):
        handler = get_handler("bank_reconciliation")
        assert handler is not None
        assert handler.validate_params({}) == []

    def test_with_customer_payments(self):
        """Customer payment path: creates invoice and registers payment."""
        client = _mock_client(post_response=sample_api_response(value={"id": 1}))
        handler = get_handler("bank_reconciliation")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "customerPayments": [
                    {
                        "customer": "Test AS",
                        "invoiceNumber": 1001,
                        "amount": 5000,
                        "date": "2026-01-15",
                    }
                ],
            },
        )
        assert result["action"] == "reconciled"
        assert len(result["payments"]) >= 1
