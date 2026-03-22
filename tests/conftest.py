"""Shared test fixtures and factories for the Tripletex AI Agent.

Provides reusable fixtures for credentials, mocked clients,
sample requests, and Tripletex-style API response builders.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.models import (
    FileAttachment,
    SolveRequest,
    TripletexCredentials,
)

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )


# ---------------------------------------------------------------------------
# Credential fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_credentials() -> dict[str, str]:
    """Return test credentials dict with base_url and session_token."""
    return {
        "base_url": "https://test-proxy.tripletex.no/v2",
        "session_token": "test-session-token-abc123",
    }


# ---------------------------------------------------------------------------
# Mock client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_api_client(fake_credentials: dict[str, str]) -> MagicMock:
    """Return a mocked TripletexClient with configurable responses.

    The mock has get/post/put/delete methods that return empty dicts
    by default. Override return_value on individual methods as needed.
    """
    from src.api_client import TripletexClient

    client = MagicMock(spec=TripletexClient)
    client.base_url = fake_credentials["base_url"]
    client.api_call_count = 0
    client.get.return_value = {"value": {}}
    client.post.return_value = {"value": {}}
    client.put.return_value = {"value": {}}
    client.delete.return_value = None
    return client


@pytest.fixture()
def mock_llm_client() -> MagicMock:
    """Return a mocked LLMClient that returns configurable classifications.

    Since LLMClient may not exist yet, we create a MagicMock without spec.
    The mock's classify method returns a default TaskClassification dict.
    """
    client = MagicMock()
    client.classify.return_value = {
        "task_type": "create_employee",
        "params": {"first_name": "Ola", "last_name": "Nordmann"},
        "confidence": 0.95,
    }
    return client


# ---------------------------------------------------------------------------
# Sample request fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_solve_request(fake_credentials: dict[str, str]) -> SolveRequest:
    """Return a valid SolveRequest for testing."""
    return SolveRequest(
        prompt="Opprett en ny ansatt med navn Ola Nordmann",
        files=[],
        tripletex_credentials=TripletexCredentials(**fake_credentials),
    )


@pytest.fixture()
def sample_solve_request_with_file(
    fake_credentials: dict[str, str],
) -> SolveRequest:
    """Return a SolveRequest with a file attachment."""
    return SolveRequest(
        prompt="Registrer denne kvitteringen som reiseregning",
        files=[
            FileAttachment(
                filename="receipt.pdf",
                content_base64="dGVzdCBjb250ZW50",  # "test content"
                mime_type="application/pdf",
            )
        ],
        tripletex_credentials=TripletexCredentials(**fake_credentials),
    )


# ---------------------------------------------------------------------------
# API response factories
# ---------------------------------------------------------------------------


def sample_api_response(
    values: list[dict[str, Any]] | None = None,
    value: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Tripletex-style API response.

    Args:
        values: List of entities (for list endpoints).
        value: Single entity (for single-resource endpoints).

    Returns a dict matching the Tripletex response shape:
    - List: {"fullResultSize": N, "from": 0, "count": N, "values": [...]}
    - Single: {"value": {...}}
    """
    if values is not None:
        return {
            "fullResultSize": len(values),
            "from": 0,
            "count": len(values),
            "values": values,
        }
    if value is not None:
        return {"value": value}
    return {"value": {}}


def sample_error_response(
    status: int = 400,
    message: str = "Validation failed",
    validation_messages: list[dict[str, str]] | None = None,
    code: int = 0,
    developer_message: str = "",
) -> dict[str, Any]:
    """Build a Tripletex-style error response with validationMessages.

    Args:
        status: HTTP status code.
        message: Error message.
        validation_messages: List of validation error dicts.
        code: Error code.
        developer_message: Developer-facing message.
    """
    resp: dict[str, Any] = {
        "status": status,
        "code": code,
        "message": message,
        "developerMessage": developer_message,
        "validationMessages": validation_messages or [],
        "requestId": "test-request-id",
    }
    return resp
