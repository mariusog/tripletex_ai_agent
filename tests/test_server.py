"""Tests for the FastAPI server endpoints."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.server import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_healthy(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestSolveEndpoint:
    @patch("src.task_router.create_router")
    def test_solve_returns_completed(self, mock_create: AsyncMock, client: TestClient) -> None:
        mock_router = AsyncMock()
        mock_create.return_value = mock_router

        response = client.post(
            "/solve",
            json={
                "prompt": "Create an employee",
                "tripletex_credentials": {
                    "base_url": "https://test.tripletex.dev/v2",
                    "session_token": "test-token",
                },
            },
        )
        assert response.status_code == 200
        assert response.json() == {"status": "completed"}

    @patch("src.task_router.create_router", side_effect=Exception("LLM down"))
    def test_solve_returns_completed_on_error(
        self, mock_create: AsyncMock, client: TestClient
    ) -> None:
        response = client.post(
            "/solve",
            json={
                "prompt": "Create an employee",
                "tripletex_credentials": {
                    "base_url": "https://test.tripletex.dev/v2",
                    "session_token": "test-token",
                },
            },
        )
        assert response.status_code == 200
        assert response.json() == {"status": "completed"}

    def test_solve_rejects_invalid_body(self, client: TestClient) -> None:
        response = client.post("/solve", json={"bad": "data"})
        assert response.status_code == 422


class TestApiKeyAuth:
    @patch.dict(os.environ, {"API_KEY": "secret-key"})
    @patch("src.task_router.create_router")
    def test_valid_api_key_accepted(self, mock_create: AsyncMock, client: TestClient) -> None:
        mock_create.return_value = AsyncMock()
        response = client.post(
            "/solve",
            json={
                "prompt": "Create employee",
                "tripletex_credentials": {
                    "base_url": "https://test.tripletex.dev/v2",
                    "session_token": "t",
                },
            },
            headers={"Authorization": "Bearer secret-key"},
        )
        assert response.status_code == 200

    @patch.dict(os.environ, {"API_KEY": "secret-key"})
    def test_invalid_api_key_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/solve",
            json={
                "prompt": "Create employee",
                "tripletex_credentials": {
                    "base_url": "https://test.tripletex.dev/v2",
                    "session_token": "t",
                },
            },
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert response.status_code == 401
