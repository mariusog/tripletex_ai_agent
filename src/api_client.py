"""Tripletex REST API client with auth, rate limiting, and error handling.

Provides a typed HTTP client that handles Basic Auth, field selection,
exponential backoff on 429s, and structured error parsing.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from src.constants import (
    API_AUTH_USERNAME,
    API_CONTENT_TYPE,
    API_RATE_LIMIT_BASE_DELAY,
    API_RATE_LIMIT_MAX_RETRIES,
    API_REQUEST_TIMEOUT,
)
from src.models import ApiError

logger = logging.getLogger(__name__)


class TripletexApiError(Exception):
    """Raised when the Tripletex API returns an error response."""

    def __init__(self, error: ApiError) -> None:
        self.error = error
        super().__init__(f"Tripletex API error {error.status}: {error.message}")


class TripletexClient:
    """HTTP client for the Tripletex REST API v2.

    Handles authentication, rate limiting, and structured error parsing.
    All API calls are logged with method, endpoint, status, and duration.
    """

    def __init__(self, base_url: str, session_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_call_count = 0
        self._client = httpx.Client(
            auth=(API_AUTH_USERNAME, session_token),
            headers={"Content-Type": API_CONTENT_TYPE},
            timeout=API_REQUEST_TIMEOUT,
        )

    @property
    def api_call_count(self) -> int:
        """Total number of API calls made (excluding retries)."""
        return self._api_call_count

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        fields: str | None = None,
    ) -> Any:
        """Send GET request with optional field selection."""
        params = dict(params or {})
        if fields:
            params["fields"] = fields
        return self._request("GET", endpoint, params=params)

    def post(
        self,
        endpoint: str,
        data: dict[str, Any] | list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send POST request with JSON body (dict or list for batch endpoints)."""
        return self._request("POST", endpoint, json_data=data, params=params)

    def put(
        self,
        endpoint: str,
        data: dict[str, Any] | list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Send PUT request with JSON body."""
        return self._request("PUT", endpoint, json_data=data, params=params)

    def delete(self, endpoint: str) -> Any:
        """Send DELETE request."""
        return self._request("DELETE", endpoint)

    def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> Any:
        """Execute HTTP request with rate limit retry and error handling."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        self._api_call_count += 1

        # Pre-validation: strip None values from POST/PUT bodies
        if json_data is not None and method in ("POST", "PUT"):
            if isinstance(json_data, dict):
                json_data = {k: v for k, v in json_data.items() if v is not None}
                if not json_data:
                    logger.warning("Empty payload after stripping None for %s %s", method, endpoint)
            elif isinstance(json_data, list):
                json_data = [
                    {k: v for k, v in item.items() if v is not None}
                    if isinstance(item, dict)
                    else item
                    for item in json_data
                ]

        start = time.monotonic()

        for attempt in range(API_RATE_LIMIT_MAX_RETRIES + 1):
            response = self._client.request(method, url, params=params, json=json_data)
            duration = time.monotonic() - start
            logger.info(
                "API %s %s -> %d (%.2fs)",
                method,
                endpoint,
                response.status_code,
                duration,
            )

            if response.status_code == 429:
                if attempt < API_RATE_LIMIT_MAX_RETRIES:
                    delay = API_RATE_LIMIT_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "Rate limited (429), retry %d/%d in %.1fs",
                        attempt + 1,
                        API_RATE_LIMIT_MAX_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                # Exhausted retries on 429
                raise TripletexApiError(self._parse_error(response, response.status_code))

            if response.status_code >= 400:
                error = self._parse_error(response, response.status_code)
                logger.warning(
                    "API error %d on %s %s: %s | validation: %s",
                    error.status,
                    method,
                    endpoint,
                    error.message,
                    error.validation_messages,
                )
                raise TripletexApiError(error)

            # Success — parse JSON if present
            if response.status_code == 204:
                return None
            return response.json()

        # Should not reach here, but handle defensively
        raise TripletexApiError(ApiError(status=429, message="Rate limit retries exhausted"))

    @staticmethod
    def _parse_error(response: httpx.Response, status_code: int) -> ApiError:
        """Parse a Tripletex error response into a structured ApiError."""
        try:
            body = response.json()
        except Exception:
            return ApiError(
                status=status_code,
                message=response.text[:200] if response.text else "Unknown",
            )

        return ApiError(
            status=status_code,
            code=body.get("code") or 0,
            message=body.get("message") or "",
            developer_message=body.get("developerMessage") or "",
            validation_messages=body.get("validationMessages") or [],
            request_id=body.get("requestId") or "",
        )
