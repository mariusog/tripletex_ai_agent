"""Tests for shared entity resolvers."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.api_client import TripletexApiError
from src.handlers.api_helpers import (
    ensure_bank_account,
    find_cost_category,
    find_invoice_id,
    find_travel_expense,
    get_travel_payment_type,
)
from src.handlers.entity_resolver import (
    _resolve_customer as resolve_customer,
)
from src.handlers.entity_resolver import (
    _resolve_product as resolve_product,
)
from src.models import ApiError
from tests.conftest import sample_api_response

# ---------------------------------------------------------------------------
# ensure_bank_account
# ---------------------------------------------------------------------------


class TestEnsureBankAccount:
    def setup_method(self):
        # Clear cache between tests
        from src.handlers.api_helpers import _bank_account_set

        _bank_account_set.clear()

    def test_skips_when_bank_account_exists(self):
        client = MagicMock()
        client.base_url = "https://test.tripletex.no/v2"
        client.get.return_value = sample_api_response(
            values=[{"id": 1, "bankAccountNumber": "12345678903", "version": 0}]
        )
        ensure_bank_account(client)
        client.put.assert_not_called()

    def test_sets_bank_account_when_missing(self):
        client = MagicMock()
        client.base_url = "https://test2.tripletex.no/v2"
        client.get.return_value = sample_api_response(
            values=[{"id": 1, "bankAccountNumber": None, "version": 0}]
        )
        ensure_bank_account(client)
        client.put.assert_called_once()

    def test_caches_per_base_url(self):
        client = MagicMock()
        client.base_url = "https://cached.tripletex.no/v2"
        client.get.return_value = sample_api_response(
            values=[{"id": 1, "bankAccountNumber": "123", "version": 0}]
        )
        ensure_bank_account(client)
        ensure_bank_account(client)
        assert client.get.call_count == 1  # Second call uses cache

    def test_handles_no_account(self):
        client = MagicMock()
        client.base_url = "https://empty.tripletex.no/v2"
        client.get.return_value = sample_api_response(values=[])
        ensure_bank_account(client)
        client.put.assert_not_called()

    def test_handles_api_error(self):
        client = MagicMock()
        client.base_url = "https://error.tripletex.no/v2"
        client.get.side_effect = TripletexApiError(ApiError(status=500, message="Server error"))
        ensure_bank_account(client)  # Should not raise


# ---------------------------------------------------------------------------
# resolve_customer
# ---------------------------------------------------------------------------


class TestResolveCustomer:
    def test_none_returns_zero(self):
        client = MagicMock()
        assert resolve_customer(client, None) == {"id": 0}

    def test_dict_with_id(self):
        client = MagicMock()
        assert resolve_customer(client, {"id": 42}) == {"id": 42}

    def test_int_value(self):
        client = MagicMock()
        assert resolve_customer(client, 5) == {"id": 5}

    def test_numeric_string(self):
        client = MagicMock()
        assert resolve_customer(client, "10") == {"id": 10}

    def test_creates_with_org_number(self):
        client = MagicMock()
        client.post.return_value = sample_api_response(value={"id": 99})
        result = resolve_customer(
            client,
            {"name": "ACME", "organizationNumber": "123456789"},
        )
        assert result == {"id": 99}

    def test_searches_then_creates_by_name(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[])
        client.post.return_value = sample_api_response(value={"id": 77})
        result = resolve_customer(client, "New Company")
        assert result == {"id": 77}

    def test_finds_by_exact_name(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 33, "name": "Target Corp"}])
        result = resolve_customer(client, "Target Corp")
        assert result == {"id": 33}


# ---------------------------------------------------------------------------
# resolve_product
# ---------------------------------------------------------------------------


class TestResolveProduct:
    def test_dict_with_id(self):
        client = MagicMock()
        assert resolve_product(client, {"id": 42}) == {"id": 42}

    def test_int_value(self):
        client = MagicMock()
        assert resolve_product(client, 7) == {"id": 7}

    def test_creates_by_name(self):
        client = MagicMock()
        client.post.return_value = sample_api_response(value={"id": 50})
        result = resolve_product(client, "Widget", price=100)
        assert result == {"id": 50}

    def test_updates_existing_on_number_conflict(self):
        client = MagicMock()
        client.post.side_effect = TripletexApiError(ApiError(status=409, message="Number taken"))
        client.get.return_value = sample_api_response(
            values=[{"id": 60, "name": "Old", "number": 1001}]
        )
        client.put.return_value = sample_api_response(value={"id": 60})
        result = resolve_product(
            client,
            {"name": "Updated", "number": 1001},
            price=200,
        )
        assert result == {"id": 60}

    def test_returns_zero_when_all_creation_fails(self):
        client = MagicMock()
        client.post.side_effect = TripletexApiError(ApiError(status=400, message="Bad request"))
        client.get.return_value = sample_api_response(values=[])
        result = resolve_product(client, {"name": ""})
        assert result == {"id": 0}


# ---------------------------------------------------------------------------
# find_cost_category
# ---------------------------------------------------------------------------


class TestFindCostCategory:
    def test_finds_by_mapped_keyword(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 1, "description": "Fly"}])
        result = find_cost_category(client, "flight")
        assert result == {"id": 1}

    def test_finds_by_partial_match(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[{"id": 2, "description": "Hotellovernatting"}]
        )
        result = find_cost_category(client, "hotell")
        assert result == {"id": 2}

    def test_falls_back_to_first(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 3, "description": "Annet"}])
        result = find_cost_category(client, "unknown stuff")
        assert result == {"id": 3}

    def test_returns_none_when_empty(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[])
        result = find_cost_category(client, "anything")
        assert result is None

    def test_uses_cache(self):
        client = MagicMock()
        cache = {"categories": [{"id": 5, "description": "Taxi"}]}
        result = find_cost_category(client, "taxi", cache)
        assert result == {"id": 5}
        client.get.assert_not_called()


# ---------------------------------------------------------------------------
# get_travel_payment_type
# ---------------------------------------------------------------------------


class TestGetTravelPaymentType:
    def test_returns_first_type(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 10}])
        assert get_travel_payment_type(client) == {"id": 10}

    def test_returns_none_when_empty(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[])
        assert get_travel_payment_type(client) is None


# ---------------------------------------------------------------------------
# find_travel_expense
# ---------------------------------------------------------------------------


class TestFindTravelExpense:
    def test_returns_travel_expense_id(self):
        client = MagicMock()
        assert find_travel_expense(client, {"travelExpenseId": 42}) == 42

    def test_returns_id(self):
        client = MagicMock()
        assert find_travel_expense(client, {"id": 99}) == 99

    def test_finds_by_title(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[{"id": 10, "title": "Oslo Trip", "employee": {}}]
        )
        assert find_travel_expense(client, {"title": "Oslo Trip"}) == 10

    def test_finds_by_employee_name_string(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[
                {
                    "id": 20,
                    "title": "Trip",
                    "employee": {"id": 1, "firstName": "Ola", "lastName": "Nordmann"},
                }
            ]
        )
        assert find_travel_expense(client, {"employee": "Ola Nordmann"}) == 20

    def test_finds_by_employee_dict(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[
                {
                    "id": 30,
                    "title": "Trip",
                    "employee": {"id": 1, "firstName": "Kari", "lastName": "Hansen"},
                }
            ]
        )
        result = find_travel_expense(
            client,
            {"employee": {"firstName": "Kari", "lastName": "Hansen"}},
        )
        assert result == 30

    def test_returns_first_when_no_match(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[{"id": 50, "title": "Generic", "employee": {}}]
        )
        assert find_travel_expense(client, {}) == 50

    def test_returns_none_when_empty(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[])
        assert find_travel_expense(client, {}) is None


# ---------------------------------------------------------------------------
# find_invoice_id
# ---------------------------------------------------------------------------


class TestFindInvoiceId:
    def test_returns_direct_invoice_id(self):
        client = MagicMock()
        assert find_invoice_id(client, {"invoiceId": 100}) == 100
        client.get.assert_not_called()

    def test_searches_by_invoice_number(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 200}])
        assert find_invoice_id(client, {"invoiceNumber": 10001}) == 200

    def test_searches_by_customer_id(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 300}])
        assert find_invoice_id(client, {"customer": 5}) == 300

    def test_customer_dict_with_id(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 400}])
        assert find_invoice_id(client, {"customer": {"id": 5}}) == 400

    def test_customer_dict_with_name_returns_none(self):
        client = MagicMock()
        assert find_invoice_id(client, {"customer": {"name": "ACME"}}) is None

    def test_no_search_params_returns_none(self):
        client = MagicMock()
        assert find_invoice_id(client, {}) is None

    def test_not_found_returns_none(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[])
        assert find_invoice_id(client, {"invoiceNumber": 99999}) is None

    def test_api_error_returns_none(self):
        client = MagicMock()
        client.get.side_effect = TripletexApiError(ApiError(status=500, message="Error"))
        assert find_invoice_id(client, {"invoiceNumber": 1}) is None
