"""Tests for the central task router module.

Validates orchestration: classify -> lookup handler -> execute -> respond.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.models import SolveRequest, TaskClassification, TripletexCredentials
from src.task_router import TaskRouter


@pytest.fixture()
def mock_llm() -> MagicMock:
    """LLMClient mock returning a create_employee classification."""
    llm = MagicMock()
    llm.classify_and_extract.return_value = [
        TaskClassification(
            task_type="create_employee",
            params={"firstName": "Ola", "lastName": "Nordmann"},
        )
    ]
    return llm


@pytest.fixture()
def mock_handler() -> MagicMock:
    """A mock handler with passing validation and successful execute."""
    handler = MagicMock()
    handler.validate_params.return_value = []
    handler.execute.return_value = {"id": 42}
    return handler


@pytest.fixture()
def sample_request() -> SolveRequest:
    """A minimal SolveRequest for testing."""
    return SolveRequest(
        prompt="Opprett ansatt Ola Nordmann",
        files=[],
        tripletex_credentials=TripletexCredentials(
            base_url="https://test.tripletex.no/v2",
            session_token="test-token",
        ),
    )


@pytest.mark.asyncio()
@patch("src.task_router.TripletexClient")
async def test_routes_to_correct_handler(
    mock_client_cls: MagicMock,
    mock_llm: MagicMock,
    mock_handler: MagicMock,
    sample_request: SolveRequest,
) -> None:
    """solve() classifies, finds the right handler, and executes it."""
    mock_client_cls.return_value = MagicMock(api_call_count=1, write_call_count=1, error_count=0)
    registry = {"create_employee": mock_handler}
    router = TaskRouter(llm_client=mock_llm, handler_registry=registry)

    result = await router.solve(sample_request)

    assert result.status == "completed"
    mock_llm.classify_and_extract.assert_called_once()
    mock_handler.validate_params.assert_called_once()
    mock_handler.execute.assert_called_once()


@pytest.mark.asyncio()
@patch("src.task_router.TripletexClient")
async def test_unknown_task_type_returns_completed(
    mock_client_cls: MagicMock,
    mock_llm: MagicMock,
    sample_request: SolveRequest,
) -> None:
    """solve() returns completed when no handler is found."""
    mock_llm.classify_and_extract.return_value = [
        TaskClassification(task_type="unknown_task", params={})
    ]
    mock_client_cls.return_value = MagicMock(api_call_count=0, write_call_count=0, error_count=0)
    router = TaskRouter(llm_client=mock_llm, handler_registry={})

    result = await router.solve(sample_request)

    assert result.status == "completed"


@pytest.mark.asyncio()
@patch("src.task_router.TripletexClient")
async def test_handles_llm_failure_gracefully(
    mock_client_cls: MagicMock,
    sample_request: SolveRequest,
) -> None:
    """solve() returns completed even when LLM fails on both attempts."""
    llm = MagicMock()
    llm.classify_and_extract.side_effect = RuntimeError("LLM down")
    mock_client_cls.return_value = MagicMock(api_call_count=0, write_call_count=0, error_count=0)
    router = TaskRouter(llm_client=llm, handler_registry={})

    result = await router.solve(sample_request)

    assert result.status == "completed"


@pytest.mark.asyncio()
@patch("src.task_router.TripletexClient")
async def test_logs_task_execution(
    mock_client_cls: MagicMock,
    mock_llm: MagicMock,
    mock_handler: MagicMock,
    sample_request: SolveRequest,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """solve() logs handler result with task_type."""
    mock_client_cls.return_value = MagicMock(api_call_count=1, write_call_count=1, error_count=0)
    registry = {"create_employee": mock_handler}
    router = TaskRouter(llm_client=mock_llm, handler_registry=registry)

    with caplog.at_level(logging.INFO, logger="src.task_router"):
        await router.solve(sample_request)

    assert "create_employee" in caplog.text
    assert "Handler result" in caplog.text


@pytest.mark.asyncio()
@patch("src.task_router.TripletexClient")
async def test_llm_retry_on_first_failure(
    mock_client_cls: MagicMock,
    mock_handler: MagicMock,
    sample_request: SolveRequest,
) -> None:
    """solve() retries LLM classification once when first attempt fails."""
    llm = MagicMock()
    classification = [TaskClassification(task_type="create_employee", params={"firstName": "Ola"})]
    llm.classify_and_extract.side_effect = [RuntimeError("transient"), classification]
    mock_client_cls.return_value = MagicMock(api_call_count=1, write_call_count=1, error_count=0)
    registry = {"create_employee": mock_handler}
    router = TaskRouter(llm_client=llm, handler_registry=registry)

    result = await router.solve(sample_request)

    assert result.status == "completed"
    assert llm.classify_and_extract.call_count == 2
    mock_handler.execute.assert_called_once()


@pytest.mark.asyncio()
@patch("src.task_router.TripletexClient")
async def test_handler_exception_still_returns_completed(
    mock_client_cls: MagicMock,
    mock_llm: MagicMock,
    mock_handler: MagicMock,
    sample_request: SolveRequest,
) -> None:
    """solve() returns completed even when handler raises an exception."""
    mock_handler.execute.side_effect = RuntimeError("API exploded")
    mock_client_cls.return_value = MagicMock(api_call_count=0, write_call_count=0, error_count=0)
    registry = {"create_employee": mock_handler}
    router = TaskRouter(llm_client=mock_llm, handler_registry=registry)

    result = await router.solve(sample_request)

    assert result.status == "completed"
