"""Tests for ledger/voucher handlers: create, delete, and reverse vouchers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.handlers.base import get_handler
from tests.conftest import sample_api_response


def _mock_client(
    get_response: dict[str, Any] | None = None,
    post_response: dict[str, Any] | None = None,
    put_response: dict[str, Any] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.get.return_value = get_response or sample_api_response(values=[])
    client.post.return_value = post_response or sample_api_response(value={"id": 1})
    client.put.return_value = put_response or sample_api_response(value={"id": 1})
    client.delete.return_value = None
    return client


class TestLedgerRegistration:
    def _ensure_imported(self) -> None:
        import src.handlers  # noqa: F401

    def test_create_voucher_registered(self):
        self._ensure_imported()
        assert get_handler("create_voucher") is not None

    def test_delete_voucher_registered(self):
        self._ensure_imported()
        assert get_handler("delete_voucher") is not None

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


class TestDeleteVoucher:
    def test_happy_path_with_id(self):
        client = _mock_client()
        handler = get_handler("delete_voucher")
        assert handler is not None
        result = handler.execute(client, {"voucherId": 100})
        assert result["id"] == 100
        assert result["action"] == "deleted"
        client.delete.assert_called_once_with("/ledger/voucher/100")

    def test_search_by_description(self):
        vouchers = [
            {"id": 10, "number": 1, "description": "Office supplies"},
            {"id": 11, "number": 2, "description": "Travel reimbursement"},
        ]
        client = _mock_client(get_response=sample_api_response(values=vouchers))
        handler = get_handler("delete_voucher")
        assert handler is not None
        result = handler.execute(client, {"description": "Travel"})
        assert result["id"] == 11
        assert result["action"] == "deleted"

    def test_search_by_number(self):
        vouchers = [{"id": 20, "number": 5, "description": "Test"}]
        client = _mock_client(get_response=sample_api_response(values=vouchers))
        handler = get_handler("delete_voucher")
        assert handler is not None
        result = handler.execute(client, {"number": 5})
        assert result["id"] == 20

    def test_fallback_to_first_result(self):
        vouchers = [{"id": 30, "number": 1, "description": "First"}]
        client = _mock_client(get_response=sample_api_response(values=vouchers))
        handler = get_handler("delete_voucher")
        assert handler is not None
        result = handler.execute(client, {})
        assert result["id"] == 30

    def test_not_found(self):
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("delete_voucher")
        assert handler is not None
        result = handler.execute(client, {})
        assert result["error"] == "not_found"

    def test_required_params_empty(self):
        handler = get_handler("delete_voucher")
        assert handler is not None
        assert handler.validate_params({}) == []

    def test_search_by_date(self):
        vouchers = [{"id": 40, "number": 1, "description": "Dated"}]
        client = _mock_client(get_response=sample_api_response(values=vouchers))
        handler = get_handler("delete_voucher")
        assert handler is not None
        result = handler.execute(client, {"date": "2026-03-20"})
        assert result["id"] == 40
        # Verify date search params were passed
        get_call = client.get.call_args
        assert get_call[1]["params"]["dateFrom"] == "2026-03-20"
        assert get_call[1]["params"]["dateTo"] == "2026-03-20"


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
