"""Tests for the Tripletex API client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.api_client import TripletexApiError, TripletexClient


@pytest.fixture
def client() -> TripletexClient:
    """Create a TripletexClient with test credentials."""
    return TripletexClient(
        base_url="https://test.tripletex.dev/v2",
        session_token="test-token-123",
    )


class TestTripletexClientInit:
    """Tests for client initialization."""

    def test_strips_trailing_slash(self) -> None:
        c = TripletexClient("https://api.example.com/v2/", "tok")
        assert c.base_url == "https://api.example.com/v2"

    def test_initial_call_count_is_zero(self, client: TripletexClient) -> None:
        assert client.api_call_count == 0


class TestGet:
    """Tests for GET requests."""

    def test_get_returns_json(self, client: TripletexClient) -> None:
        response = httpx.Response(200, json={"value": {"id": 1, "name": "Test"}})
        with patch.object(client._client, "request", return_value=response):
            result = client.get("/employee/1")
        assert result == {"value": {"id": 1, "name": "Test"}}
        assert client.api_call_count == 1

    def test_get_with_fields(self, client: TripletexClient) -> None:
        response = httpx.Response(200, json={"value": {"id": 1}})
        with patch.object(client._client, "request", return_value=response) as mock:
            client.get("/employee", fields="id,firstName,lastName")
        _, kwargs = mock.call_args
        assert kwargs["params"]["fields"] == "id,firstName,lastName"

    def test_get_with_params(self, client: TripletexClient) -> None:
        response = httpx.Response(200, json={"values": []})
        with patch.object(client._client, "request", return_value=response) as mock:
            client.get("/employee", params={"from": 0, "count": 10})
        _, kwargs = mock.call_args
        assert kwargs["params"]["from"] == 0
        assert kwargs["params"]["count"] == 10


class TestPost:
    """Tests for POST requests."""

    def test_post_sends_json_body(self, client: TripletexClient) -> None:
        response = httpx.Response(201, json={"value": {"id": 42, "firstName": "Jane"}})
        data = {"firstName": "Jane", "lastName": "Doe"}
        with patch.object(client._client, "request", return_value=response) as mock:
            result = client.post("/employee", data=data)
        mock.assert_called_once()
        _, kwargs = mock.call_args
        assert kwargs["json"] == data
        assert result["value"]["id"] == 42


class TestPut:
    """Tests for PUT requests."""

    def test_put_sends_json_body(self, client: TripletexClient) -> None:
        response = httpx.Response(200, json={"value": {"id": 1}})
        data = {"firstName": "Updated"}
        with patch.object(client._client, "request", return_value=response) as mock:
            client.put("/employee/1", data=data)
        _, kwargs = mock.call_args
        assert kwargs["json"] == data


class TestDelete:
    """Tests for DELETE requests."""

    def test_delete_204_returns_none(self, client: TripletexClient) -> None:
        response = httpx.Response(204)
        with patch.object(client._client, "request", return_value=response):
            result = client.delete("/employee/1")
        assert result is None


class TestErrorHandling:
    """Tests for error response parsing."""

    def test_400_raises_api_error(self, client: TripletexClient) -> None:
        body = {
            "status": 400,
            "code": 4000,
            "message": "Bad Request",
            "developerMessage": "Missing required field",
            "validationMessages": [{"field": "name", "message": "Required"}],
        }
        response = httpx.Response(400, json=body)
        with (
            patch.object(client._client, "request", return_value=response),
            pytest.raises(TripletexApiError) as exc_info,
        ):
            client.get("/employee")
        err = exc_info.value.error
        assert err.status == 400
        assert err.developer_message == "Missing required field"
        assert len(err.validation_messages) == 1

    def test_404_raises_without_retry(self, client: TripletexClient) -> None:
        response = httpx.Response(404, json={"status": 404, "message": "NF"})
        with (
            patch.object(client._client, "request", return_value=response) as mock,
            pytest.raises(TripletexApiError),
        ):
            client.get("/employee/999")
        # Should NOT retry on 4xx
        assert mock.call_count == 1

    def test_non_json_error_body(self, client: TripletexClient) -> None:
        response = httpx.Response(500, text="Internal Server Error")
        with (
            patch.object(client._client, "request", return_value=response),
            pytest.raises(TripletexApiError) as exc_info,
        ):
            client.get("/employee")
        assert exc_info.value.error.status == 500


class TestRateLimiting:
    """Tests for 429 rate limit handling."""

    @patch("src.api_client.time.sleep")
    def test_retries_on_429_then_succeeds(
        self, mock_sleep: MagicMock, client: TripletexClient
    ) -> None:
        r429 = httpx.Response(429, json={"status": 429, "message": "Slow"})
        r200 = httpx.Response(200, json={"value": {"id": 1}})
        with patch.object(client._client, "request", side_effect=[r429, r200]):
            result = client.get("/employee/1")
        assert result["value"]["id"] == 1
        mock_sleep.assert_called_once_with(1.0)

    @patch("src.api_client.time.sleep")
    def test_exhausts_retries_on_429(self, mock_sleep: MagicMock, client: TripletexClient) -> None:
        r429 = httpx.Response(429, json={"status": 429, "message": "Slow"})
        with (
            patch.object(client._client, "request", return_value=r429),
            pytest.raises(TripletexApiError) as exc_info,
        ):
            client.get("/employee")
        assert exc_info.value.error.status == 429
        # 3 retries = 3 sleeps
        assert mock_sleep.call_count == 3

    @patch("src.api_client.time.sleep")
    def test_exponential_backoff_delays(
        self, mock_sleep: MagicMock, client: TripletexClient
    ) -> None:
        r429 = httpx.Response(429, json={"status": 429, "message": "Slow"})
        r200 = httpx.Response(200, json={"value": {}})
        with patch.object(client._client, "request", side_effect=[r429, r429, r200]):
            client.get("/employee")
        # Delays: 1.0, 2.0
        assert mock_sleep.call_args_list[0][0][0] == 1.0
        assert mock_sleep.call_args_list[1][0][0] == 2.0


class TestCallCount:
    """Tests for API call counting."""

    def test_tracks_multiple_calls(self, client: TripletexClient) -> None:
        response = httpx.Response(200, json={"value": {}})
        with patch.object(client._client, "request", return_value=response):
            client.get("/a")
            client.post("/b", data={})
            client.put("/c", data={})
        assert client.api_call_count == 3

    @patch("src.api_client.time.sleep")
    def test_retries_do_not_increase_count(
        self, mock_sleep: MagicMock, client: TripletexClient
    ) -> None:
        r429 = httpx.Response(429, json={"status": 429, "message": "Slow"})
        r200 = httpx.Response(200, json={"value": {}})
        with patch.object(client._client, "request", side_effect=[r429, r200]):
            client.get("/employee")
        # Only 1 logical call, even though 2 HTTP requests
        assert client.api_call_count == 1
