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
        handler = get_handler("create_voucher")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "date": "2026-03-20",
                "description": "Test voucher",
                "postings": [
                    {"account": 1920, "amount": 1000, "debit": True},
                    {"account": 3000, "amount": 1000, "credit": True},
                ],
            },
        )
        assert result["id"] == 100
        assert result["action"] == "created"
        body = client.post.call_args[1]["data"]
        assert body["date"] == "2026-03-20"
        assert len(body["postings"]) == 2
        # Debit posting should have positive amount
        assert body["postings"][0]["account"] == {"id": 1920}
        assert body["postings"][0]["amountGross"] == 1000
        # Credit posting should have negative amount
        assert body["postings"][1]["amountGross"] == -1000

    def test_minimal_params(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 101}))
        handler = get_handler("create_voucher")
        assert handler is not None
        result = handler.execute(client, {"date": "2026-01-01"})
        assert result["id"] == 101
        body = client.post.call_args[1]["data"]
        assert body == {"date": "2026-01-01"}

    def test_required_params(self):
        handler = get_handler("create_voucher")
        assert handler is not None
        assert handler.validate_params({}) == ["date"]


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
        assert handler.validate_params({}) == ["voucherId"]
