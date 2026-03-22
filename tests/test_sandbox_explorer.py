"""Tests for the sandbox explorer module.

Verifies field discovery via GET probes and required-field extraction
from POST validation errors, plus manifest generation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.api_client import TripletexApiError
from src.models import ApiError
from src.sandbox_explorer import (
    EndpointInfo,
    FieldInfo,
    SandboxExplorer,
    _extract_sample_entity,
    _infer_type,
    generate_manifest_json,
    generate_manifest_md,
)


@pytest.fixture()
def mock_client() -> MagicMock:
    """Return a mock TripletexClient."""
    from src.api_client import TripletexClient

    client = MagicMock(spec=TripletexClient)
    return client


class TestInferType:
    """Tests for the _infer_type helper."""

    def test_infer_type_string(self) -> None:
        assert _infer_type("hello") == "string"

    def test_infer_type_integer(self) -> None:
        assert _infer_type(42) == "integer"

    def test_infer_type_float(self) -> None:
        assert _infer_type(3.14) == "number"

    def test_infer_type_boolean(self) -> None:
        assert _infer_type(True) == "boolean"

    def test_infer_type_none(self) -> None:
        assert _infer_type(None) == "nullable"

    def test_infer_type_dict(self) -> None:
        assert _infer_type({"id": 1}) == "object"

    def test_infer_type_list(self) -> None:
        assert _infer_type([1, 2]) == "array"

    def test_infer_type_date(self) -> None:
        assert _infer_type("2025-01-15") == "date"


class TestExtractSampleEntity:
    """Tests for extracting entities from API responses."""

    def test_extract_from_list_response(self) -> None:
        response = {"values": [{"id": 1, "name": "Test"}], "count": 1}
        assert _extract_sample_entity(response) == {"id": 1, "name": "Test"}

    def test_extract_from_single_response(self) -> None:
        response = {"value": {"id": 1, "name": "Test"}}
        assert _extract_sample_entity(response) == {"id": 1, "name": "Test"}

    def test_extract_from_empty_list(self) -> None:
        response = {"values": [], "count": 0}
        assert _extract_sample_entity(response) is None

    def test_extract_from_empty_value(self) -> None:
        response = {"value": {}}
        assert _extract_sample_entity(response) is None

    def test_extract_from_non_dict(self) -> None:
        assert _extract_sample_entity("not a dict") is None


class TestSandboxExplorerProbeGet:
    """Tests for GET field discovery."""

    def test_probe_get_discovers_fields(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = {
            "values": [{"id": 1, "name": "Ola", "active": True, "startDate": "2025-01-01"}]
        }
        explorer = SandboxExplorer(mock_client)
        info = explorer._explore_endpoint("/employee")
        assert "id" in info.get_fields
        assert "name" in info.get_fields
        assert info.field_details["id"].field_type == "integer"
        assert info.field_details["name"].field_type == "string"
        assert info.field_details["active"].field_type == "boolean"
        assert info.field_details["startDate"].field_type == "date"

    def test_probe_get_handles_error(self, mock_client: MagicMock) -> None:
        mock_client.get.side_effect = TripletexApiError(
            ApiError(status=401, message="Unauthorized")
        )
        mock_client.post.side_effect = TripletexApiError(
            ApiError(status=401, message="Unauthorized")
        )
        explorer = SandboxExplorer(mock_client)
        info = explorer._explore_endpoint("/employee")
        assert info.get_error != ""
        assert info.get_fields == []


class TestSandboxExplorerProbePost:
    """Tests for POST validation error discovery."""

    def test_probe_post_discovers_required_fields(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = {"values": []}
        mock_client.post.side_effect = TripletexApiError(
            ApiError(
                status=422,
                message="Validation failed",
                validation_messages=[
                    {"field": "name", "message": "is required"},
                    {"field": "startDate", "message": "must be a valid date"},
                ],
            )
        )
        explorer = SandboxExplorer(mock_client)
        info = explorer._explore_endpoint("/employee")
        assert "name" in info.required_fields
        assert "startDate" in info.required_fields
        assert info.field_details["name"].required is True
        assert info.field_details["name"].validation_message == "is required"

    def test_probe_post_handles_empty_validation(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = {"values": []}
        mock_client.post.side_effect = TripletexApiError(
            ApiError(status=400, message="Bad request", validation_messages=[])
        )
        explorer = SandboxExplorer(mock_client)
        info = explorer._explore_endpoint("/employee")
        assert info.required_fields == []

    def test_probe_post_success_with_empty_body(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = {"values": []}
        mock_client.post.return_value = {"value": {"id": 1}}
        explorer = SandboxExplorer(mock_client)
        info = explorer._explore_endpoint("/employee")
        assert info.required_fields == []
        assert info.post_error == ""


class TestExploreAll:
    """Tests for exploring all endpoints."""

    def test_explore_all_iterates_endpoints(self, mock_client: MagicMock) -> None:
        mock_client.get.return_value = {"values": []}
        mock_client.post.side_effect = TripletexApiError(
            ApiError(status=400, message="Bad request")
        )
        explorer = SandboxExplorer(mock_client)
        results = explorer.explore_all()
        assert len(results) == 14  # All configured endpoints
        assert "/employee" in results
        assert "/ledger/account" in results


class TestManifestGeneration:
    """Tests for JSON and Markdown manifest output."""

    def _sample_results(self) -> dict[str, EndpointInfo]:
        info = EndpointInfo(endpoint="/employee")
        info.get_fields = ["id", "name"]
        info.required_fields = ["name"]
        info.field_details = {
            "id": FieldInfo(name="id", field_type="integer"),
            "name": FieldInfo(
                name="name",
                field_type="string",
                required=True,
                validation_message="is required",
            ),
        }
        return {"/employee": info}

    def test_generate_manifest_json(self) -> None:
        results = self._sample_results()
        json_str = generate_manifest_json(results)
        parsed = __import__("json").loads(json_str)
        assert "/employee" in parsed
        assert parsed["/employee"]["required_fields"] == ["name"]
        assert parsed["/employee"]["field_details"]["name"]["required"] is True

    def test_generate_manifest_md_contains_table(self) -> None:
        results = self._sample_results()
        md = generate_manifest_md(results)
        assert "## `/employee`" in md
        assert "| name | string | yes | is required |" in md
        assert "**Required fields:** name" in md

    def test_generate_manifest_md_empty_endpoint(self) -> None:
        results = {"/empty": EndpointInfo(endpoint="/empty")}
        md = generate_manifest_md(results)
        assert "_No fields discovered._" in md


class TestEndpointInfoToDict:
    """Tests for EndpointInfo serialization."""

    def test_to_dict_includes_all_keys(self) -> None:
        info = EndpointInfo(endpoint="/test")
        result = info.to_dict()
        assert "endpoint" in result
        assert "get_fields" in result
        assert "required_fields" in result
        assert "field_details" in result
        assert "validation_messages" in result
