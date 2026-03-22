"""Tests for delete handlers: search-then-delete for all entity types."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.api_client import TripletexApiError
from src.handlers.base import get_handler
from src.models import ApiError
from tests.conftest import sample_api_response


def _mock_client(get_values=None):
    client = MagicMock()
    client.get.return_value = sample_api_response(values=get_values or [])
    client.delete.return_value = None
    return client


# ---------------------------------------------------------------------------
# _find_entity and _do_delete helpers
# ---------------------------------------------------------------------------


class TestFindEntity:
    def test_returns_id_when_provided(self):
        from src.handlers.delete import _find_entity

        client = _mock_client()
        assert _find_entity(client, "/customer", {"id": 42}) == 42
        client.get.assert_not_called()

    def test_finds_by_exact_name_match(self):
        from src.handlers.delete import _find_entity

        client = _mock_client(
            get_values=[
                {"id": 1, "name": "Other"},
                {"id": 2, "name": "Target"},
            ]
        )
        assert _find_entity(client, "/customer", {"name": "Target"}) == 2

    def test_case_insensitive_match(self):
        from src.handlers.delete import _find_entity

        client = _mock_client(get_values=[{"id": 5, "name": "ACME Corp"}])
        assert _find_entity(client, "/customer", {"name": "acme corp"}) == 5

    def test_returns_none_when_no_match(self):
        from src.handlers.delete import _find_entity

        client = _mock_client(get_values=[{"id": 1, "name": "Other"}])
        assert _find_entity(client, "/customer", {"name": "Missing"}) is None

    def test_returns_none_when_no_name(self):
        from src.handlers.delete import _find_entity

        client = _mock_client()
        assert _find_entity(client, "/customer", {}) is None

    def test_handles_api_error(self):
        from src.handlers.delete import _find_entity

        client = MagicMock()
        client.get.side_effect = TripletexApiError(ApiError(status=500, message="Server error"))
        assert _find_entity(client, "/customer", {"name": "Test"}) is None


class TestDoDelete:
    def test_successful_delete(self):
        from src.handlers.delete import _do_delete

        client = _mock_client()
        result = _do_delete(client, "/customer", 42, "customer")
        assert result == {"id": 42, "action": "deleted"}
        client.delete.assert_called_once_with("/customer/42")

    def test_delete_api_error(self):
        from src.handlers.delete import _do_delete

        client = MagicMock()
        client.delete.side_effect = TripletexApiError(ApiError(status=404, message="Not found"))
        result = _do_delete(client, "/customer", 42, "customer")
        assert result["id"] == 42
        assert "error" in result


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestDeleteRegistration:
    def _ensure_imported(self):
        import src.handlers  # noqa: F401

    def test_delete_customer_registered(self):
        self._ensure_imported()
        assert get_handler("delete_customer") is not None

    def test_delete_product_registered(self):
        self._ensure_imported()
        assert get_handler("delete_product") is not None

    def test_delete_department_registered(self):
        self._ensure_imported()
        assert get_handler("delete_department") is not None

    def test_delete_project_registered(self):
        self._ensure_imported()
        assert get_handler("delete_project") is not None

    def test_delete_order_registered(self):
        self._ensure_imported()
        assert get_handler("delete_order") is not None

    def test_delete_travel_expense_registered(self):
        self._ensure_imported()
        assert get_handler("delete_travel_expense") is not None

    def test_delete_supplier_registered(self):
        self._ensure_imported()
        assert get_handler("delete_supplier") is not None

    def test_delete_voucher_registered(self):
        self._ensure_imported()
        assert get_handler("delete_voucher") is not None


# ---------------------------------------------------------------------------
# DeleteCustomer
# ---------------------------------------------------------------------------


class TestDeleteCustomer:
    def test_happy_path(self):
        client = _mock_client(get_values=[{"id": 10, "name": "ACME"}])
        handler = get_handler("delete_customer")
        result = handler.execute(client, {"name": "ACME"})
        assert result == {"id": 10, "action": "deleted"}

    def test_not_found(self):
        client = _mock_client(get_values=[])
        handler = get_handler("delete_customer")
        result = handler.execute(client, {"name": "Missing"})
        assert result == {"error": "not_found"}


# ---------------------------------------------------------------------------
# DeleteProduct
# ---------------------------------------------------------------------------


class TestDeleteProduct:
    def test_by_id(self):
        client = _mock_client()
        handler = get_handler("delete_product")
        result = handler.execute(client, {"id": 99})
        assert result == {"id": 99, "action": "deleted"}

    def test_by_number(self):
        client = _mock_client(get_values=[{"id": 55}])
        handler = get_handler("delete_product")
        result = handler.execute(client, {"number": "1001"})
        assert result == {"id": 55, "action": "deleted"}

    def test_not_found(self):
        client = _mock_client(get_values=[])
        handler = get_handler("delete_product")
        result = handler.execute(client, {"name": "Missing"})
        assert result == {"error": "not_found"}


# ---------------------------------------------------------------------------
# DeleteOrder
# ---------------------------------------------------------------------------


class TestDeleteOrder:
    def test_happy_path(self):
        client = _mock_client()
        handler = get_handler("delete_order")
        result = handler.execute(client, {"id": 123})
        assert result == {"id": 123, "action": "deleted"}


# ---------------------------------------------------------------------------
# DeleteTravelExpense
# ---------------------------------------------------------------------------


class TestDeleteTravelExpense:
    def test_by_id(self):
        client = _mock_client()
        handler = get_handler("delete_travel_expense")
        result = handler.execute(client, {"id": 77})
        assert result == {"id": 77, "action": "deleted"}

    def test_by_travel_expense_id(self):
        client = _mock_client()
        handler = get_handler("delete_travel_expense")
        result = handler.execute(client, {"travelExpenseId": 88})
        assert result == {"id": 88, "action": "deleted"}

    def test_by_title(self):
        client = _mock_client(get_values=[{"id": 33, "title": "Oslo Trip"}])
        handler = get_handler("delete_travel_expense")
        result = handler.execute(client, {"title": "Oslo Trip"})
        assert result == {"id": 33, "action": "deleted"}

    def test_not_found(self):
        client = _mock_client(get_values=[])
        handler = get_handler("delete_travel_expense")
        result = handler.execute(client, {"title": "Missing"})
        assert result == {"error": "not_found"}


# ---------------------------------------------------------------------------
# DeleteVoucher
# ---------------------------------------------------------------------------


class TestDeleteVoucher:
    def test_by_id(self):
        client = _mock_client()
        handler = get_handler("delete_voucher")
        result = handler.execute(client, {"id": 200})
        assert result == {"id": 200, "action": "deleted"}

    def test_by_voucher_id(self):
        client = _mock_client()
        handler = get_handler("delete_voucher")
        result = handler.execute(client, {"voucherId": 201})
        assert result == {"id": 201, "action": "deleted"}

    def test_by_number_search(self):
        client = _mock_client(get_values=[{"id": 300, "number": 5}])
        handler = get_handler("delete_voucher")
        result = handler.execute(client, {"number": 5})
        assert result == {"id": 300, "action": "deleted"}

    def test_not_found(self):
        client = _mock_client(get_values=[])
        handler = get_handler("delete_voucher")
        result = handler.execute(client, {"number": 9999})
        assert result == {"error": "not_found"}
