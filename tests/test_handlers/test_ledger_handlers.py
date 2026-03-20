"""Tests for ledger/voucher handlers: create and reverse vouchers."""

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


class TestLedgerRegistration:
    def _ensure_imported(self) -> None:
        import src.handlers  # noqa: F401

    def test_create_voucher_registered(self):
        self._ensure_imported()
        assert get_handler("create_voucher") is not None

    def test_reverse_voucher_registered(self):
        self._ensure_imported()
        assert get_handler("reverse_voucher") is not None


class TestCreateVoucher:
    def test_happy_path(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 100}))
        # Mock account lookup
        client.get.return_value = sample_api_response(values=[{"id": 999}])
        handler = get_handler("create_voucher")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "date": "2026-03-20",
                "description": "Test voucher",
                "postings": [
                    {"account": 1920, "debit": 1000},
                    {"account": 3000, "credit": 1000},
                ],
            },
        )
        assert result["id"] == 100
        assert result["action"] == "created"

    def test_minimal_params(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 101}))
        handler = get_handler("create_voucher")
        assert handler is not None
        result = handler.execute(client, {"date": "2026-01-01"})
        assert result["id"] == 101

    def test_required_params(self):
        handler = get_handler("create_voucher")
        assert handler is not None
        assert handler.validate_params({}) == []


class TestReverseVoucher:
    def test_happy_path(self):
        client = _mock_client()
        handler = get_handler("reverse_voucher")
        assert handler is not None
        result = handler.execute(client, {"voucherId": 100, "date": "2026-03-20"})
        assert result["id"] == 100
        assert result["action"] == "reversed"
        client.put.assert_called_once()
        endpoint = client.put.call_args[0][0]
        assert "/:reverse" in endpoint

    def test_required_params(self):
        handler = get_handler("reverse_voucher")
        assert handler is not None
        assert handler.validate_params({}) == []
