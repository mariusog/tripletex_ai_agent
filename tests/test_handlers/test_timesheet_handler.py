"""Tests for timesheet handler: log hours and optionally invoice."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.api_client import TripletexApiError
from src.handlers.base import get_handler
from src.models import ApiError
from tests.conftest import sample_api_response


def _mock_resolve(_client, entity_type, _value, **_kw):
    """Mock resolve that returns different IDs per entity type."""
    return {"id": {"employee": 1, "customer": 2, "activity": 3}.get(entity_type, 0)}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestCreateActivity:
    @patch("src.handlers.timesheet.resolve", return_value={"id": 10})
    def test_creates_new_activity(self, _mock_resolve):
        from src.handlers.timesheet import _create_activity

        client = MagicMock()
        client.post.return_value = sample_api_response(value={"id": 10})
        result = _create_activity(client, "Consulting")
        assert result == {"id": 10}

    @patch("src.handlers.timesheet.resolve", return_value={"id": 5})
    def test_falls_back_to_search_on_duplicate(self, _mock_resolve):
        from src.handlers.timesheet import _create_activity

        client = MagicMock()
        result = _create_activity(client, "Consulting")
        assert result == {"id": 5}

    @patch("src.handlers.timesheet.resolve", return_value={"id": 0})
    def test_returns_zero_id_when_not_found(self, _mock_resolve):
        from src.handlers.timesheet import _create_activity

        client = MagicMock()
        result = _create_activity(client, "Missing")
        assert result == {"id": 0}


class TestCreateProject:
    def test_creates_new_project(self):
        from src.handlers.timesheet import _create_project

        client = MagicMock()
        client.post.return_value = sample_api_response(value={"id": 20})
        result = _create_project(client, "Web App", {"id": 1}, {"id": 2})
        assert result == {"id": 20}

    def test_falls_back_to_search_on_error(self):
        from src.handlers.timesheet import _create_project

        client = MagicMock()
        client.post.side_effect = TripletexApiError(ApiError(status=409, message="Exists"))
        client.get.return_value = sample_api_response(values=[{"id": 15, "name": "Web App"}])
        result = _create_project(client, "Web App")
        assert result == {"id": 15}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestTimesheetRegistration:
    def test_log_timesheet_registered(self):
        import src.handlers  # noqa: F401

        assert get_handler("log_timesheet") is not None


# ---------------------------------------------------------------------------
# LogTimesheetHandler
# ---------------------------------------------------------------------------


class TestLogTimesheetHandler:
    @patch("src.handlers.timesheet.resolve", return_value={"id": 1})
    def test_happy_path_minimal(self, _mock_resolve):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 1}])
        client.post.return_value = sample_api_response(value={"id": 100})

        handler = get_handler("log_timesheet")
        result = handler.execute(
            client,
            {"employee": "Ola Nordmann", "hours": 8, "date": "2026-03-01"},
        )
        assert result["entryId"] == 100
        assert result["action"] == "timesheet_logged"
        assert result["invoiceId"] is None

    @patch("src.handlers.timesheet.resolve", side_effect=_mock_resolve)
    def test_with_project_and_activity(self, _mock_resolve):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 1}])
        client.post.return_value = sample_api_response(value={"id": 200})

        handler = get_handler("log_timesheet")
        result = handler.execute(
            client,
            {
                "employee": {"firstName": "Ola", "lastName": "Nordmann"},
                "customer": "Test AS",
                "project": "WebApp",
                "activity": "Development",
                "hours": 4,
            },
        )
        assert result["entryId"] == 200
        assert result["action"] == "timesheet_logged"

    @patch("src.handlers.timesheet.ensure_bank_account")
    @patch("src.handlers.timesheet.resolve", side_effect=_mock_resolve)
    def test_generates_invoice_with_hourly_rate(self, _resolve, _bank):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 1}])
        client.post.return_value = sample_api_response(value={"id": 300})

        handler = get_handler("log_timesheet")
        result = handler.execute(
            client,
            {
                "employee": 1,
                "customer": "Test AS",
                "project": "Invoiceable",
                "activity": "Consulting",
                "hours": 10,
                "hourlyRate": 1500,
            },
        )
        assert result["action"] == "timesheet_logged"
        assert result["invoiceId"] is not None

    @patch("src.handlers.timesheet.resolve", return_value={"id": 1})
    def test_timesheet_entry_failure(self, _mock_resolve):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 1}])
        client.post.side_effect = TripletexApiError(ApiError(status=400, message="Bad request"))

        handler = get_handler("log_timesheet")
        result = handler.execute(client, {"employee": 1, "hours": 8})
        assert result["entryId"] is None

    @patch("src.handlers.timesheet.resolve", return_value={"id": 1})
    def test_dict_project_and_activity(self, _mock_resolve):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 1}])
        client.post.return_value = sample_api_response(value={"id": 400})

        handler = get_handler("log_timesheet")
        result = handler.execute(
            client,
            {
                "employee": 1,
                "project": {"name": "MyProject"},
                "activity": {"name": "MyActivity"},
                "hours": 2,
            },
        )
        assert result["entryId"] == 400
