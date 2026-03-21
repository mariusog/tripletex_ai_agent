"""Tests for previously untested handlers: T120 (Tier 3), T121 (Tier 2), T122 (Tier 1)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from src.handlers.base import get_handler
from tests.conftest import sample_api_response


def _mock_client(
    get_response: dict[str, Any] | None = None,
    post_response: dict[str, Any] | None = None,
    put_response: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock TripletexClient with canned responses."""
    client = MagicMock()
    client.get.return_value = get_response or sample_api_response(values=[])
    client.post.return_value = post_response or sample_api_response(value={"id": 1})
    client.put.return_value = put_response or sample_api_response(value={"id": 1})
    client.delete.return_value = None
    return client


def _ensure_imported() -> None:
    import src.handlers  # noqa: F401


# ---------------------------------------------------------------------------
# T120: Tier 3 handlers (x3 multiplier)
# ---------------------------------------------------------------------------


class TestBalanceSheetReport:
    def test_happy_path(self):
        _ensure_imported()
        entries = [
            {"account": {"id": 1}, "balanceOut": 50000},
            {"account": {"id": 2}, "balanceOut": -30000},
        ]
        client = _mock_client(get_response=sample_api_response(values=entries))
        handler = get_handler("balance_sheet_report")
        assert handler is not None
        result = handler.execute(client, {"dateFrom": "2025-01-01", "dateTo": "2025-12-31"})
        assert result["action"] == "report_retrieved"
        assert result["count"] == 2
        assert len(result["entries"]) == 2
        client.get.assert_called_once()
        call_kwargs = client.get.call_args
        assert call_kwargs[1]["params"]["dateFrom"] == "2025-01-01"
        assert call_kwargs[1]["params"]["dateTo"] == "2025-12-31"

    def test_with_account_range(self):
        _ensure_imported()
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("balance_sheet_report")
        assert handler is not None
        handler.execute(
            client,
            {
                "dateFrom": "2025-01-01",
                "dateTo": "2025-12-31",
                "accountNumberFrom": 1000,
                "accountNumberTo": 1999,
            },
        )
        query = client.get.call_args[1]["params"]
        assert query["accountNumberFrom"] == 1000
        assert query["accountNumberTo"] == 1999


class TestBankReconciliation:
    def test_basic_fallback(self):
        _ensure_imported()
        client = MagicMock()
        client.base_url = "https://test.tripletex.no/v2"
        client.get.return_value = sample_api_response(values=[{"id": 42}])
        client.get_cached.return_value = sample_api_response(values=[{"id": 42}])
        client.post.return_value = sample_api_response(value={"id": 100})
        handler = get_handler("bank_reconciliation")
        assert handler is not None
        result = handler.execute(client, {"accountNumber": "1920"})
        assert result["id"] == 100
        assert result["action"] == "created"


class TestLedgerCorrection:
    def test_happy_path_with_postings(self):
        _ensure_imported()
        client = MagicMock()
        # _build_posting calls _resolve_account which calls client.get
        client.get.return_value = sample_api_response(values=[{"id": 100, "vatType": None}])
        client.post.return_value = sample_api_response(value={"id": 55})
        handler = get_handler("ledger_correction")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "date": "2025-06-15",
                "description": "Fix posting error",
                "postings": [
                    {"account": 4000, "debit": 1000},
                    {"account": 1920, "credit": 1000},
                ],
            },
        )
        assert result["id"] == 55
        assert result["action"] == "correction_created"
        client.post.assert_called_once()
        endpoint = client.post.call_args[0][0]
        assert "/ledger/voucher" in endpoint

    def test_reverses_original_voucher_if_provided(self):
        _ensure_imported()
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 100, "vatType": None}])
        client.put.return_value = sample_api_response(value={"id": 10})
        client.post.return_value = sample_api_response(value={"id": 56})
        handler = get_handler("ledger_correction")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "date": "2025-06-15",
                "originalVoucherId": 10,
                "postings": [{"account": 4000, "debit": 500}],
            },
        )
        assert result["id"] == 56
        # Should have called PUT to reverse original
        client.put.assert_called_once()
        reverse_endpoint = client.put.call_args[0][0]
        assert "/ledger/voucher/10/:reverse" in reverse_endpoint


class TestYearEndClosing:
    def test_happy_path_with_postings(self):
        _ensure_imported()
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 100, "vatType": None}])
        client.post.return_value = sample_api_response(value={"id": 77})
        handler = get_handler("year_end_closing")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "year": 2025,
                "postings": [
                    {"account": 3000, "credit": 100000},
                    {"account": 8800, "debit": 100000},
                ],
            },
        )
        assert result["id"] == 77
        assert result["year"] == 2025
        assert result["action"] == "year_end_closed"
        body = client.post.call_args[1]["data"]
        assert body["date"] == "2025-12-31"
        assert "sendToLedger" in str(client.post.call_args)

    def test_auto_generates_closing_from_balance_sheet(self):
        _ensure_imported()
        client = MagicMock()
        # GETs: balance sheet, all accounts (VAT lookup), equity account,
        #       balance sheet (tax calc), tax account 8700, tax account 2920
        client.get.side_effect = [
            sample_api_response(
                values=[
                    {"account": {"id": 301}, "balanceOut": -50000},
                    {"account": {"id": 401}, "balanceOut": 30000},
                ]
            ),
            sample_api_response(
                values=[
                    {"id": 301, "number": 3000, "vatType": {"id": 3}},
                    {"id": 401, "number": 7000, "vatType": None},
                ]
            ),
            sample_api_response(values=[{"id": 205}]),  # equity 2050
            sample_api_response(values=[{"balanceOut": -20000}]),  # tax P&L
            sample_api_response(values=[{"id": 870, "number": 8700}]),  # acct 8700
            sample_api_response(values=[{"id": 292, "number": 2920}]),  # acct 2920
        ]
        client.get_cached.return_value = sample_api_response(values=[{"id": 870, "number": 8700}])
        client.post.return_value = sample_api_response(value={"id": 78})
        handler = get_handler("year_end_closing")
        assert handler is not None
        result = handler.execute(client, {"year": 2025})
        assert result["id"] == 78
        assert result["action"] == "year_end_closed"
        body = client.post.call_args[1]["data"]
        assert len(body["postings"]) >= 3  # 2 account closings + 1 equity + optional tax


class TestReverseVoucher:
    def test_happy_path_with_id(self):
        _ensure_imported()
        client = MagicMock()
        client.get.return_value = sample_api_response(value={"id": 20})
        client.put.return_value = sample_api_response(value={"id": 20})
        handler = get_handler("reverse_voucher")
        assert handler is not None
        result = handler.execute(client, {"voucherId": 20, "date": "2025-06-01"})
        assert result["id"] == 20
        assert result["action"] == "reversed"
        client.put.assert_called_once()
        endpoint = client.put.call_args[0][0]
        assert "/ledger/voucher/20/:reverse" in endpoint

    def test_voucher_not_found(self):
        _ensure_imported()
        from src.api_client import TripletexApiError

        client = MagicMock()
        api_err = TripletexApiError.__new__(TripletexApiError)
        api_err.status_code = 404
        api_err.error = MagicMock()
        api_err.error.message = "Not found"
        # First GET (verify) raises, second GET (search) returns empty
        client.get.side_effect = [
            api_err,
            sample_api_response(values=[]),
        ]
        handler = get_handler("reverse_voucher")
        assert handler is not None
        result = handler.execute(client, {"voucherId": 999})
        assert result.get("error") == "voucher_not_found"


class TestDeleteVoucher:
    def test_happy_path_with_id(self):
        _ensure_imported()
        client = _mock_client()
        handler = get_handler("delete_voucher")
        assert handler is not None
        result = handler.execute(client, {"voucherId": 15})
        assert result["id"] == 15
        assert result["action"] == "deleted"
        client.delete.assert_called_once()
        endpoint = client.delete.call_args[0][0]
        assert "/ledger/voucher/15" in endpoint

    def test_search_by_number(self):
        _ensure_imported()
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 33, "number": 5}])
        client.delete.return_value = None
        handler = get_handler("delete_voucher")
        assert handler is not None
        result = handler.execute(client, {"voucherNumber": 5})
        assert result["id"] == 33
        assert result["action"] == "deleted"

    def test_not_found(self):
        _ensure_imported()
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("delete_voucher")
        assert handler is not None
        result = handler.execute(client, {"voucherNumber": 999})
        assert result.get("error") == "not_found"


# ---------------------------------------------------------------------------
# T121: Tier 2 handlers (x2 multiplier)
# ---------------------------------------------------------------------------


class TestCreateAsset:
    def test_happy_path(self):
        _ensure_imported()
        client = _mock_client(post_response=sample_api_response(value={"id": 10}))
        handler = get_handler("create_asset")
        assert handler is not None
        result = handler.execute(client, {"name": "Office Laptop"})
        assert result["id"] == 10
        assert result["action"] == "created"
        client.post.assert_called_once()
        endpoint = client.post.call_args[0][0]
        assert "/asset" in endpoint

    def test_with_optional_fields(self):
        _ensure_imported()
        client = _mock_client()
        handler = get_handler("create_asset")
        assert handler is not None
        handler.execute(
            client,
            {
                "name": "Printer",
                "acquisitionDate": "2025-01-15",
                "acquisitionCost": 5000,
                "depreciationPercentage": 20,
            },
        )
        body = client.post.call_args[1]["data"]
        assert body["name"] == "Printer"
        assert body["acquisitionCost"] == 5000
        assert body["depreciationPercentage"] == 20


class TestUpdateAsset:
    def test_happy_path_by_id(self):
        _ensure_imported()
        client = MagicMock()
        client.get.return_value = sample_api_response(
            value={"id": 5, "name": "Old Laptop", "version": 0}
        )
        client.put.return_value = sample_api_response(value={"id": 5})
        handler = get_handler("update_asset")
        assert handler is not None
        result = handler.execute(client, {"assetId": 5, "name": "New Laptop"})
        assert result["id"] == 5
        assert result["action"] == "updated"
        body = client.put.call_args[1]["data"]
        assert body["name"] == "New Laptop"

    def test_not_found(self):
        _ensure_imported()
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("update_asset")
        assert handler is not None
        result = handler.execute(client, {"name": "NonExistent"})
        assert result.get("error") == "asset_not_found"


class TestApproveTravelExpense:
    @patch("src.handlers.travel._find_travel_expense", return_value=42)
    def test_happy_path(self, mock_find):
        _ensure_imported()
        client = _mock_client(put_response=sample_api_response(value={"id": 42}))
        handler = get_handler("approve_travel_expense")
        assert handler is not None
        result = handler.execute(client, {"travelExpenseId": 42})
        assert result["id"] == 42
        assert result["action"] == "approved"
        client.put.assert_called_once()
        endpoint = client.put.call_args[0][0]
        assert "/:approve" in endpoint

    @patch("src.handlers.travel._find_travel_expense", return_value=None)
    def test_not_found_no_employee(self, mock_find):
        _ensure_imported()
        client = _mock_client()
        handler = get_handler("approve_travel_expense")
        assert handler is not None
        result = handler.execute(client, {})
        assert result.get("error") == "travel_expense_not_found"


class TestDeliverTravelExpense:
    @patch("src.handlers.travel._find_travel_expense", return_value=30)
    def test_happy_path(self, mock_find):
        _ensure_imported()
        client = _mock_client(put_response=sample_api_response(value={"id": 30}))
        handler = get_handler("deliver_travel_expense")
        assert handler is not None
        result = handler.execute(client, {"travelExpenseId": 30})
        assert result["id"] == 30
        assert result["action"] == "delivered"
        client.put.assert_called_once()
        endpoint = client.put.call_args[0][0]
        assert "/:deliver" in endpoint

    @patch("src.handlers.travel._find_travel_expense", return_value=None)
    def test_not_found_no_employee(self, mock_find):
        _ensure_imported()
        client = _mock_client()
        handler = get_handler("deliver_travel_expense")
        assert handler is not None
        result = handler.execute(client, {})
        assert result.get("error") == "travel_expense_not_found"


# ---------------------------------------------------------------------------
# T122: Tier 1 handlers (x1 multiplier)
# ---------------------------------------------------------------------------


class TestAssignRole:
    def test_happy_path_by_id(self):
        _ensure_imported()
        client = MagicMock()
        client.get.return_value = sample_api_response(
            value={
                "id": 7,
                "firstName": "Kari",
                "lastName": "Hansen",
                "version": 0,
            }
        )
        client.put.return_value = sample_api_response(value={"id": 7})
        handler = get_handler("assign_role")
        assert handler is not None
        result = handler.execute(client, {"employee": 7, "role": "administrator"})
        assert result["id"] == 7
        assert result["action"] == "role_assigned"
        body = client.put.call_args[1]["data"]
        assert body.get("allowInformationRegistration") is True
        assert "userType" not in body  # userType is create-only, stripped on PUT

    def test_employee_not_found(self):
        _ensure_imported()
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("assign_role")
        assert handler is not None
        result = handler.execute(client, {"employee": "Ghost Person", "role": "admin"})
        assert result.get("error") == "employee_not_found"


class TestEnableModule:
    def test_happy_path(self):
        _ensure_imported()
        client = MagicMock()
        client.get.return_value = sample_api_response(
            value={"moduleProject": False, "moduleDepartment": True}
        )
        client.put.return_value = sample_api_response(
            value={"moduleProject": True, "moduleDepartment": True}
        )
        handler = get_handler("enable_module")
        assert handler is not None
        result = handler.execute(client, {"moduleName": "moduleProject"})
        assert result["moduleName"] == "moduleProject"
        assert result["action"] == "enabled"
        body = client.put.call_args[1]["data"]
        assert body["moduleProject"] is True


class TestUpdateCustomerHandler:
    def test_happy_path(self):
        _ensure_imported()
        cust = {"id": 3, "name": "Acme AS", "email": "old@acme.no"}
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[cust])
        client.put.return_value = sample_api_response(value={"id": 3})
        handler = get_handler("update_customer")
        assert handler is not None
        result = handler.execute(client, {"name": "Acme AS", "email": "new@acme.no"})
        assert result["id"] == 3
        assert result["action"] == "updated"
        body = client.put.call_args[1]["data"]
        assert body["email"] == "new@acme.no"

    def test_not_found(self):
        _ensure_imported()
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("update_customer")
        assert handler is not None
        result = handler.execute(client, {"name": "Ghost Corp"})
        assert result.get("error") == "not_found"


class TestUpdateEmployeeHandler:
    def test_happy_path(self):
        _ensure_imported()
        emp = {"id": 8, "firstName": "Per", "lastName": "Olsen"}
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[emp])
        client.put.return_value = sample_api_response(value={"id": 8})
        handler = get_handler("update_employee")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "firstName": "Per",
                "lastName": "Olsen",
                "phoneNumberMobile": "99887766",
            },
        )
        assert result["id"] == 8
        assert result["action"] == "updated"
        body = client.put.call_args[1]["data"]
        assert body["phoneNumberMobile"] == "99887766"

    def test_not_found(self):
        _ensure_imported()
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("update_employee")
        assert handler is not None
        result = handler.execute(client, {"firstName": "Nobody", "lastName": "Here"})
        assert result.get("error") == "not_found"
