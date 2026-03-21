"""Tests for salary/payroll handler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.api_client import TripletexApiError
from src.handlers.base import get_handler
from src.models import ApiError
from tests.conftest import sample_api_response

# ---------------------------------------------------------------------------
# _find_salary_type
# ---------------------------------------------------------------------------


class TestFindSalaryType:
    def test_finds_by_keyword_mapping(self):
        from src.handlers.salary import _find_salary_type

        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[{"id": 10, "number": "1000", "name": "Fastlønn"}]
        )
        result = _find_salary_type(client, "base salary")
        assert result == {"id": 10}

    def test_finds_by_name_match(self):
        from src.handlers.salary import _find_salary_type

        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[{"id": 20, "number": "2000", "name": "Feriepenger"}]
        )
        result = _find_salary_type(client, "feriepenger")
        assert result == {"id": 20}

    def test_falls_back_to_first_type(self):
        from src.handlers.salary import _find_salary_type

        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[{"id": 30, "number": "1000", "name": "Fastlønn"}]
        )
        result = _find_salary_type(client, "unknown description")
        assert result == {"id": 30}

    def test_returns_none_when_no_types(self):
        from src.handlers.salary import _find_salary_type

        client = MagicMock()
        client.get.return_value = sample_api_response(values=[])
        result = _find_salary_type(client, "anything")
        assert result is None

    def test_uses_cache(self):
        from src.handlers.salary import _find_salary_type

        client = MagicMock()
        cache = {"types": [{"id": 5, "number": "1000", "name": "Fastlønn"}]}
        result = _find_salary_type(client, "fastlønn", cache)
        assert result == {"id": 5}
        client.get.assert_not_called()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestSalaryRegistration:
    def test_run_payroll_registered(self):
        import src.handlers  # noqa: F401

        assert get_handler("run_payroll") is not None


# ---------------------------------------------------------------------------
# RunPayrollHandler
# ---------------------------------------------------------------------------


class TestRunPayrollHandler:
    @patch("src.handlers.salary.resolve_employee", return_value={"id": 1})
    @patch("src.handlers.salary._find_salary_type", return_value={"id": 10})
    def test_happy_path_base_salary(self, _mock_type, _mock_emp):
        client = MagicMock()
        client.post.return_value = sample_api_response(value={"id": 500})

        handler = get_handler("run_payroll")
        result = handler.execute(
            client,
            {
                "employee": "Ola Nordmann",
                "baseSalary": 50000,
                "month": 3,
                "year": 2026,
            },
        )
        assert result["id"] == 500
        assert result["action"] == "payroll_created"

    @patch("src.handlers.salary.resolve_employee", return_value={"id": 1})
    @patch("src.handlers.salary._find_salary_type", return_value={"id": 10})
    def test_with_bonus(self, _mock_type, _mock_emp):
        client = MagicMock()
        client.post.return_value = sample_api_response(value={"id": 501})

        handler = get_handler("run_payroll")
        result = handler.execute(
            client,
            {
                "employee": 1,
                "baseSalary": 40000,
                "bonus": 10000,
            },
        )
        assert result["id"] == 501
        assert result["action"] == "payroll_created"

    @patch("src.handlers.salary.resolve_employee", return_value={"id": 1})
    @patch("src.handlers.salary._find_salary_type", return_value={"id": 10})
    def test_with_extras(self, _mock_type, _mock_emp):
        client = MagicMock()
        client.post.return_value = sample_api_response(value={"id": 502})

        handler = get_handler("run_payroll")
        result = handler.execute(
            client,
            {
                "employee": 1,
                "salary": 30000,
                "extras": [{"amount": 5000, "description": "Overtid"}],
            },
        )
        assert result["id"] == 502

    @patch("src.handlers.salary.resolve_employee", return_value={"id": 1})
    def test_no_salary_lines_returns_error(self, _mock_emp):
        client = MagicMock()
        handler = get_handler("run_payroll")
        result = handler.execute(client, {"employee": 1})
        assert result == {"error": "no_salary_lines"}

    @patch("src.handlers.salary.resolve_employee", return_value={"id": 1})
    @patch("src.handlers.salary._find_salary_type", return_value={"id": 10})
    def test_api_error_returns_error(self, _mock_type, _mock_emp):
        client = MagicMock()
        client.post.side_effect = TripletexApiError(ApiError(status=400, message="Bad request"))

        handler = get_handler("run_payroll")
        result = handler.execute(
            client,
            {
                "employee": 1,
                "baseSalary": 50000,
            },
        )
        assert "error" in result

    @patch("src.handlers.salary.resolve_employee", return_value={"id": 1})
    @patch("src.handlers.salary._find_salary_type", return_value={"id": 10})
    def test_extras_as_single_dict(self, _mock_type, _mock_emp):
        client = MagicMock()
        client.post.return_value = sample_api_response(value={"id": 503})

        handler = get_handler("run_payroll")
        result = handler.execute(
            client,
            {
                "employee": 1,
                "baseSalary": 30000,
                "extras": {"amount": 2000, "description": "Tillegg"},
            },
        )
        assert result["id"] == 503
