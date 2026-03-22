"""Tests for project linking and activity handlers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.handlers.base import get_handler
from tests.conftest import sample_api_response
from tests.test_handlers.conftest import make_project


def _mock_client(
    get_response: dict[str, Any] | None = None,
    post_response: dict[str, Any] | None = None,
    put_response: dict[str, Any] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.get.return_value = get_response or sample_api_response(values=[])
    client.post.return_value = post_response or sample_api_response(value={"id": 1})
    client.put.return_value = put_response or sample_api_response(value={"id": 1})
    return client


class TestProjectLinkingRegistration:
    def _ensure_imported(self) -> None:
        import src.handlers  # noqa: F401

    def test_link_project_customer_registered(self):
        self._ensure_imported()
        assert get_handler("link_project_customer") is not None

    def test_create_activity_registered(self):
        self._ensure_imported()
        assert get_handler("create_activity") is not None


class TestLinkProjectCustomer:
    def test_happy_path(self):
        proj = make_project(project_id=5)
        client = _mock_client(
            get_response=sample_api_response(value=proj),
        )
        handler = get_handler("link_project_customer")
        assert handler is not None
        result = handler.execute(client, {"projectId": 5, "customer": 10})
        assert result["id"] == 5
        assert result["action"] == "customer_linked"
        put_body = client.put.call_args[1]["data"]
        assert put_body["customer"] == {"id": 10}

    def test_search_by_name(self):
        proj = make_project(project_id=7)
        proj["name"] = "Alpha"
        client = _mock_client(
            get_response=sample_api_response(values=[proj]),
        )
        handler = get_handler("link_project_customer")
        assert handler is not None
        result = handler.execute(client, {"name": "Alpha", "customer": 10})
        assert result["id"] == 7
        assert result["action"] == "customer_linked"

    def test_project_not_found(self):
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("link_project_customer")
        assert handler is not None
        result = handler.execute(client, {"customer": 1})
        assert result.get("error") == "project_not_found"

    def test_required_params(self):
        handler = get_handler("link_project_customer")
        assert handler is not None
        missing = handler.validate_params({})
        assert "customer" in missing


class TestCreateActivity:
    def test_happy_path(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 20}))
        handler = get_handler("create_activity")
        assert handler is not None
        result = handler.execute(
            client,
            {"name": "Development", "number": "A01", "isProjectActivity": True},
        )
        assert result["id"] == 20
        assert result["action"] == "created"
        body = client.post.call_args[1]["data"]
        assert body["name"] == "Development"
        assert body["number"] == "A01"
        assert body["isProjectActivity"] is True

    def test_minimal_params(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 21}))
        handler = get_handler("create_activity")
        assert handler is not None
        result = handler.execute(client, {"name": "Meeting"})
        assert result["id"] == 21
        body = client.post.call_args[1]["data"]
        assert body["name"] == "Meeting"
        assert body["activityType"] == "PROJECT_GENERAL_ACTIVITY"
