"""Tests for Tier 1 CRUD handlers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.handlers.base import get_handler
from tests.conftest import sample_api_response
from tests.test_handlers.conftest import (
    make_customer,
    make_employee,
)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


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


class TestTier1Registration:
    """Ensure all Tier 1 handlers are registered after import."""

    @pytest.fixture(autouse=True)
    def _import_handlers(self):
        import src.handlers  # noqa: F401

    @pytest.mark.parametrize(
        "task_type",
        [
            "create_employee",
            "update_employee",
            "create_customer",
            "update_customer",
            "create_product",
            "create_department",
            "create_project",
        ],
    )
    def test_handler_registered(self, task_type: str):
        handler = get_handler(task_type)
        assert handler is not None, f"No handler for {task_type}"
        assert handler.get_task_type() == task_type


# ---------------------------------------------------------------------------
# validate_params
# ---------------------------------------------------------------------------


class TestValidateParams:
    def test_missing_params_detected(self):
        handler = get_handler("create_employee")
        assert handler is not None
        missing = handler.validate_params({})
        assert "firstName" in missing
        assert "lastName" in missing

    def test_all_present(self):
        handler = get_handler("create_employee")
        assert handler is not None
        assert handler.validate_params({"firstName": "A", "lastName": "B"}) == []


# ---------------------------------------------------------------------------
# Employee
# ---------------------------------------------------------------------------


class TestCreateEmployee:
    def test_happy_path(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 42}))
        handler = get_handler("create_employee")
        assert handler is not None
        result = handler.execute(client, {"firstName": "Ola", "lastName": "Nordmann"})
        assert result["id"] == 42
        assert result["action"] == "created"
        client.post.assert_called_once()

    def test_optional_fields_included(self):
        client = _mock_client()
        handler = get_handler("create_employee")
        assert handler is not None
        handler.execute(client, {"firstName": "A", "lastName": "B", "email": "a@b.com"})
        body = client.post.call_args[1]["data"]
        assert body["email"] == "a@b.com"


class TestUpdateEmployee:
    def test_happy_path(self):
        emp = make_employee(employee_id=10)
        client = _mock_client(
            get_response=sample_api_response(values=[emp]),
            put_response=sample_api_response(value={"id": 10}),
        )
        handler = get_handler("update_employee")
        assert handler is not None
        result = handler.execute(
            client, {"firstName": "Ola", "lastName": "Nordmann", "email": "new@test.com"}
        )
        assert result["id"] == 10
        assert result["action"] == "updated"

    def test_not_found(self):
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("update_employee")
        assert handler is not None
        result = handler.execute(client, {"firstName": "X", "lastName": "Y"})
        assert result.get("error") == "not_found"


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------


class TestCreateCustomer:
    def test_happy_path(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 5}))
        handler = get_handler("create_customer")
        assert handler is not None
        result = handler.execute(client, {"name": "Acme Corp"})
        assert result["id"] == 5

    def test_optional_fields(self):
        client = _mock_client()
        handler = get_handler("create_customer")
        assert handler is not None
        handler.execute(client, {"name": "X", "email": "x@y.com", "phoneNumber": "123"})
        body = client.post.call_args[1]["data"]
        assert body["email"] == "x@y.com"
        assert body["phoneNumber"] == "123"


class TestUpdateCustomer:
    def test_happy_path(self):
        cust = make_customer(customer_id=3)
        client = _mock_client(
            get_response=sample_api_response(values=[cust]),
            put_response=sample_api_response(value={"id": 3}),
        )
        handler = get_handler("update_customer")
        assert handler is not None
        result = handler.execute(client, {"name": "Test Bedrift AS", "email": "new@co.com"})
        assert result["id"] == 3

    def test_not_found(self):
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("update_customer")
        assert handler is not None
        result = handler.execute(client, {"name": "Ghost"})
        assert result.get("error") == "not_found"


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------


class TestCreateProduct:
    def test_happy_path(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 7}))
        handler = get_handler("create_product")
        assert handler is not None
        result = handler.execute(client, {"name": "Widget"})
        assert result["id"] == 7

    def test_vat_type_as_int(self):
        client = _mock_client()
        handler = get_handler("create_product")
        assert handler is not None
        handler.execute(client, {"name": "W", "vatType": 3})
        body = client.post.call_args[1]["data"]
        assert body["vatType"] == {"id": 3}


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------


class TestCreateDepartment:
    def test_happy_path(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 2}))
        handler = get_handler("create_department")
        assert handler is not None
        result = handler.execute(client, {"name": "Engineering"})
        assert result["id"] == 2

    def test_with_manager_ref(self):
        client = _mock_client()
        handler = get_handler("create_department")
        assert handler is not None
        handler.execute(client, {"name": "D", "departmentManager": 99})
        body = client.post.call_args[1]["data"]
        assert body["departmentManager"] == {"id": 99}


class TestUpdateDepartment:
    def test_happy_path(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[{"id": 5, "name": "Sales", "version": 0}]
        )
        client.put.return_value = sample_api_response(value={"id": 5})
        handler = get_handler("update_department")
        assert handler is not None
        result = handler.execute(client, {"name": "Sales", "newName": "Marketing"})
        assert result["id"] == 5
        assert result["action"] == "updated"

    def test_not_found(self):
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[])
        handler = get_handler("update_department")
        assert handler is not None
        result = handler.execute(client, {"name": "Missing"})
        assert result == {"error": "not_found"}


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


class TestCreateProject:
    def test_happy_path(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 11}))
        client.get.return_value = sample_api_response(values=[{"id": 1}])
        handler = get_handler("create_project")
        assert handler is not None
        result = handler.execute(client, {"name": "Proj", "number": "P001"})
        assert result["id"] == 11

    def test_with_optional_refs(self):
        client = _mock_client()
        handler = get_handler("create_project")
        assert handler is not None
        handler.execute(
            client,
            {
                "name": "P",
                "number": "1",
                "projectManager": 1,
                "customer": 5,
                "startDate": "2026-01-01",
            },
        )
        body = client.post.call_args[1]["data"]
        assert body["customer"] == {"id": 5}
        assert body["startDate"] == "2026-01-01"
