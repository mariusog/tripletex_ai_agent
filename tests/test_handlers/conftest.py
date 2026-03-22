"""Handler-specific test fixtures and entity factories.

Provides pre-configured mocks and factory functions for building
common Tripletex entities used across handler tests.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.api_client import TripletexClient
from tests.conftest import sample_api_response

# ---------------------------------------------------------------------------
# Handler-level mock client
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_handler_client() -> MagicMock:
    """Pre-configured API client mock for handler tests.

    Returns a MagicMock with spec=TripletexClient. GET returns empty
    list responses by default; POST/PUT return single-value responses.
    """
    client = MagicMock(spec=TripletexClient)
    client.base_url = "https://test-proxy.tripletex.no/v2"
    client.api_call_count = 0
    client.get.return_value = sample_api_response(values=[])
    client.post.return_value = sample_api_response(value={"id": 1})
    client.put.return_value = sample_api_response(value={"id": 1})
    client.delete.return_value = None
    return client


# ---------------------------------------------------------------------------
# Entity factories
# ---------------------------------------------------------------------------


def make_employee(
    employee_id: int = 1,
    first_name: str = "Ola",
    last_name: str = "Nordmann",
    email: str = "ola.nordmann@example.com",
    **overrides: Any,
) -> dict[str, Any]:
    """Build a Tripletex employee entity dict."""
    entity: dict[str, Any] = {
        "id": employee_id,
        "firstName": first_name,
        "lastName": last_name,
        "email": email,
    }
    entity.update(overrides)
    return entity


def make_customer(
    customer_id: int = 1,
    name: str = "Test Bedrift AS",
    email: str = "post@testbedrift.no",
    **overrides: Any,
) -> dict[str, Any]:
    """Build a Tripletex customer entity dict."""
    entity: dict[str, Any] = {
        "id": customer_id,
        "name": name,
        "email": email,
    }
    entity.update(overrides)
    return entity


def make_product(
    product_id: int = 1,
    name: str = "Test Produkt",
    price: float = 100.0,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a Tripletex product entity dict."""
    entity: dict[str, Any] = {
        "id": product_id,
        "name": name,
        "priceExcludingVatCurrency": price,
    }
    entity.update(overrides)
    return entity


def make_department(
    department_id: int = 1,
    name: str = "Salg",
    department_number: int = 100,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a Tripletex department entity dict."""
    entity: dict[str, Any] = {
        "id": department_id,
        "name": name,
        "departmentNumber": department_number,
    }
    entity.update(overrides)
    return entity


def make_project(
    project_id: int = 1,
    name: str = "Test Prosjekt",
    number: str = "P001",
    project_manager_id: int = 1,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a Tripletex project entity dict."""
    entity: dict[str, Any] = {
        "id": project_id,
        "name": name,
        "number": number,
        "projectManager": {"id": project_manager_id},
    }
    entity.update(overrides)
    return entity


def make_invoice(
    invoice_id: int = 1,
    invoice_number: int = 10001,
    amount: float = 1000.0,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a Tripletex invoice entity dict."""
    entity: dict[str, Any] = {
        "id": invoice_id,
        "invoiceNumber": invoice_number,
        "amount": amount,
    }
    entity.update(overrides)
    return entity


def make_order(
    order_id: int = 1,
    order_number: str = "SO-001",
    customer_id: int = 1,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a Tripletex order entity dict."""
    entity: dict[str, Any] = {
        "id": order_id,
        "number": order_number,
        "customer": {"id": customer_id},
    }
    entity.update(overrides)
    return entity
