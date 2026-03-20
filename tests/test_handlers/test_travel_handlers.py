"""Tests for travel expense handlers: create, delete, deliver, approve."""

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


class TestTravelRegistration:
    def _ensure_imported(self) -> None:
        import src.handlers  # noqa: F401

    def test_create_travel_expense_registered(self):
        self._ensure_imported()
        assert get_handler("create_travel_expense") is not None

    def test_delete_travel_expense_registered(self):
        self._ensure_imported()
        assert get_handler("delete_travel_expense") is not None

    def test_deliver_travel_expense_registered(self):
        self._ensure_imported()
        assert get_handler("deliver_travel_expense") is not None

    def test_approve_travel_expense_registered(self):
        self._ensure_imported()
        assert get_handler("approve_travel_expense") is not None


class TestCreateTravelExpense:
    def test_happy_path(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 10}))
        handler = get_handler("create_travel_expense")
        assert handler is not None
        result = handler.execute(
            client,
            {"employee": 5, "title": "Conference trip", "project": 3},
        )
        assert result["id"] == 10
        assert result["action"] == "created"
        body = client.post.call_args[1]["data"]
        assert body["employee"] == {"id": 5}
        assert body["project"] == {"id": 3}
        assert body["title"] == "Conference trip"

    def test_with_costs_and_per_diem(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 11}))
        # Mock GET for payment type and cost categories
        client.get.return_value = sample_api_response(values=[{"id": 100}])
        handler = get_handler("create_travel_expense")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "employee": 1,
                "costs": [{"description": "Fly", "amount": 500}],
            },
        )
        assert result["id"] == 11
        # First post = travel expense, second = cost
        assert client.post.call_count >= 2

    def test_required_params(self):
        handler = get_handler("create_travel_expense")
        assert handler is not None
        assert handler.validate_params({}) == ["employee"]
        assert handler.validate_params({"employee": 1}) == []


class TestDeliverTravelExpense:
    def test_happy_path(self):
        client = _mock_client()
        handler = get_handler("deliver_travel_expense")
        assert handler is not None
        result = handler.execute(client, {"travelExpenseId": 10})
        assert result["id"] == 10
        assert result["action"] == "delivered"
        client.put.assert_called_once()


class TestDeleteTravelExpense:
    def test_happy_path_with_id(self):
        client = _mock_client()
        handler = get_handler("delete_travel_expense")
        assert handler is not None
        result = handler.execute(client, {"travelExpenseId": 10})
        assert result["id"] == 10
        assert result["action"] == "deleted"
        client.delete.assert_called_once_with("/travelExpense/10")

    def test_search_by_title(self):
        expenses = [
            {"id": 1, "title": "Oslo trip"},
            {"id": 2, "title": "Bergen conference"},
        ]
        client = _mock_client(get_response=sample_api_response(values=expenses))
        handler = get_handler("delete_travel_expense")
        assert handler is not None
        result = handler.execute(client, {"title": "Bergen"})
        assert result["id"] == 2
        assert result["action"] == "deleted"

    def test_fallback_to_first_result(self):
        expenses = [{"id": 99, "title": "Some trip"}]
        client = _mock_client(get_response=sample_api_response(values=expenses))
        handler = get_handler("delete_travel_expense")
        assert handler is not None
        result = handler.execute(client, {})
        assert result["id"] == 99

    def test_not_found(self):
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("delete_travel_expense")
        assert handler is not None
        result = handler.execute(client, {})
        assert result["error"] == "not_found"

    def test_required_params_empty(self):
        handler = get_handler("delete_travel_expense")
        assert handler is not None
        assert handler.validate_params({}) == []


class TestApproveTravelExpense:
    def test_happy_path(self):
        client = _mock_client()
        handler = get_handler("approve_travel_expense")
        assert handler is not None
        result = handler.execute(client, {"travelExpenseId": 10})
        assert result["id"] == 10
        assert result["action"] == "approved"
        client.put.assert_called_once()
