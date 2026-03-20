"""Tests for newly added handlers: module, asset, reporting, update_project."""

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
    """Create a mock TripletexClient with canned responses."""
    client = MagicMock()
    client.get.return_value = get_response or sample_api_response(values=[])
    client.post.return_value = post_response or sample_api_response(value={"id": 1})
    client.put.return_value = put_response or sample_api_response(value={"id": 1})
    return client


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestNewHandlerRegistration:
    """Verify all new handlers are registered."""

    def test_enable_module_registered(self) -> None:
        assert get_handler("enable_module") is not None

    def test_assign_role_registered(self) -> None:
        assert get_handler("assign_role") is not None

    def test_create_asset_registered(self) -> None:
        assert get_handler("create_asset") is not None

    def test_update_asset_registered(self) -> None:
        assert get_handler("update_asset") is not None

    def test_update_project_registered(self) -> None:
        assert get_handler("update_project") is not None

    def test_ledger_correction_registered(self) -> None:
        assert get_handler("ledger_correction") is not None

    def test_year_end_closing_registered(self) -> None:
        assert get_handler("year_end_closing") is not None

    def test_balance_sheet_report_registered(self) -> None:
        assert get_handler("balance_sheet_report") is not None

    def test_bank_reconciliation_registered(self) -> None:
        assert get_handler("bank_reconciliation") is not None


# ---------------------------------------------------------------------------
# EnableModuleHandler
# ---------------------------------------------------------------------------


class TestEnableModuleHandler:
    def test_enable_module_happy_path(self) -> None:
        handler = get_handler("enable_module")
        assert handler is not None
        client = _mock_client(
            get_response=sample_api_response(value={}),
            put_response=sample_api_response(value={"moduleProject": True}),
        )
        result = handler.execute(client, {"moduleName": "moduleProject"})
        assert result["action"] == "enabled"
        assert result["moduleName"] == "moduleProject"
        client.put.assert_called_once()


# ---------------------------------------------------------------------------
# AssignRoleHandler
# ---------------------------------------------------------------------------


class TestAssignRoleHandler:
    def test_assign_role_by_id(self) -> None:
        handler = get_handler("assign_role")
        assert handler is not None
        emp = {"id": 5, "firstName": "Ola", "lastName": "N"}
        client = _mock_client(
            get_response=sample_api_response(value=emp),
            put_response=sample_api_response(value=emp),
        )
        result = handler.execute(client, {"employee": 5, "role": "admin"})
        assert result["action"] == "role_assigned"
        assert result["id"] == 5

    def test_assign_role_not_found(self) -> None:
        handler = get_handler("assign_role")
        assert handler is not None
        client = _mock_client(get_response=sample_api_response(values=[]))
        result = handler.execute(client, {"employee": "Unknown", "role": "admin"})
        assert result["error"] == "employee_not_found"


# ---------------------------------------------------------------------------
# CreateAssetHandler
# ---------------------------------------------------------------------------


class TestCreateAssetHandler:
    def test_create_asset_happy_path(self) -> None:
        handler = get_handler("create_asset")
        assert handler is not None
        client = _mock_client(post_response=sample_api_response(value={"id": 10}))
        result = handler.execute(
            client,
            {"name": "Office Chair", "acquisitionCost": 5000, "acquisitionDate": "2025-01-15"},
        )
        assert result["id"] == 10
        assert result["action"] == "created"
        client.post.assert_called_once()

    def test_create_asset_with_refs(self) -> None:
        handler = get_handler("create_asset")
        assert handler is not None
        client = _mock_client(post_response=sample_api_response(value={"id": 11}))
        result = handler.execute(
            client,
            {"name": "Laptop", "account": 1200, "department": 3},
        )
        assert result["id"] == 11
        call_data = client.post.call_args[1].get("data") or client.post.call_args[0][1]
        # Verify refs were resolved
        assert isinstance(call_data, dict)


# ---------------------------------------------------------------------------
# UpdateAssetHandler
# ---------------------------------------------------------------------------


class TestUpdateAssetHandler:
    def test_update_asset_happy_path(self) -> None:
        handler = get_handler("update_asset")
        assert handler is not None
        asset = {"id": 10, "name": "Old Chair"}
        client = _mock_client(
            get_response=sample_api_response(value=asset),
            put_response=sample_api_response(value={"id": 10, "name": "New Chair"}),
        )
        result = handler.execute(client, {"assetId": 10, "name": "New Chair"})
        assert result["id"] == 10
        assert result["action"] == "updated"

    def test_update_asset_by_name(self) -> None:
        handler = get_handler("update_asset")
        assert handler is not None
        asset = {"id": 10, "name": "Printer"}
        client = _mock_client(
            get_response=sample_api_response(values=[asset]),
            put_response=sample_api_response(value={"id": 10, "name": "Printer"}),
        )
        result = handler.execute(client, {"name": "Printer", "description": "Updated"})
        assert result["id"] == 10
        assert result["action"] == "updated"

    def test_update_asset_not_found(self) -> None:
        handler = get_handler("update_asset")
        assert handler is not None
        client = _mock_client(get_response=sample_api_response(values=[]))
        result = handler.execute(client, {"name": "Nonexistent"})
        assert result["error"] == "asset_not_found"


# ---------------------------------------------------------------------------
# UpdateProjectHandler
# ---------------------------------------------------------------------------


class TestUpdateProjectHandler:
    def test_update_project_happy_path(self) -> None:
        handler = get_handler("update_project")
        assert handler is not None
        proj = {"id": 1, "name": "Old Name", "number": "P001", "projectManager": {"id": 1}}
        client = _mock_client(
            get_response=sample_api_response(value=proj),
            put_response=sample_api_response(value={**proj, "name": "New Name"}),
        )
        result = handler.execute(client, {"projectId": 1, "name": "New Name"})
        assert result["id"] == 1
        assert result["action"] == "updated"

    def test_update_project_by_name(self) -> None:
        handler = get_handler("update_project")
        assert handler is not None
        proj = {"id": 3, "name": "Alpha", "number": "P003", "projectManager": {"id": 1}}
        client = _mock_client(
            get_response=sample_api_response(values=[proj]),
            put_response=sample_api_response(value={**proj, "isClosed": True}),
        )
        result = handler.execute(client, {"name": "Alpha", "isClosed": True})
        assert result["id"] == 3
        assert result["action"] == "updated"

    def test_update_project_not_found(self) -> None:
        handler = get_handler("update_project")
        assert handler is not None
        client = _mock_client(get_response=sample_api_response(values=[]))
        result = handler.execute(client, {"name": "Nonexistent"})
        assert result["error"] == "project_not_found"


# ---------------------------------------------------------------------------
# LedgerCorrectionHandler
# ---------------------------------------------------------------------------


class TestLedgerCorrectionHandler:
    def test_correction_happy_path(self) -> None:
        handler = get_handler("ledger_correction")
        assert handler is not None
        client = _mock_client(post_response=sample_api_response(value={"id": 20}))
        result = handler.execute(
            client,
            {
                "date": "2025-03-20",
                "description": "Fix posting error",
                "postings": [
                    {"account": 1000, "amountGross": 500},
                    {"account": 2000, "amountGross": -500},
                ],
            },
        )
        assert result["id"] == 20
        assert result["action"] == "correction_created"


# ---------------------------------------------------------------------------
# YearEndClosingHandler
# ---------------------------------------------------------------------------


class TestYearEndClosingHandler:
    def test_year_end_happy_path(self) -> None:
        handler = get_handler("year_end_closing")
        assert handler is not None
        client = _mock_client(post_response=sample_api_response(value={"id": 30}))
        result = handler.execute(client, {"year": 2025})
        assert result["id"] == 30
        assert result["year"] == 2025
        assert result["action"] == "year_end_closed"


# ---------------------------------------------------------------------------
# BalanceSheetReportHandler
# ---------------------------------------------------------------------------


class TestBalanceSheetReportHandler:
    def test_balance_sheet_happy_path(self) -> None:
        handler = get_handler("balance_sheet_report")
        assert handler is not None
        entries = [{"account": "1000", "balance": 50000}]
        client = _mock_client(get_response=sample_api_response(values=entries))
        result = handler.execute(
            client,
            {"dateFrom": "2025-01-01", "dateTo": "2025-12-31"},
        )
        assert result["action"] == "report_retrieved"
        assert result["count"] == 1
        assert len(result["entries"]) == 1
