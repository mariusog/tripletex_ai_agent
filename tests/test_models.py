"""Tests for Pydantic models in src/models.py.

Covers serialization, deserialization, optional fields,
and file attachment handling for all public models.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import (
    ApiError,
    FileAttachment,
    SolveRequest,
    SolveResponse,
    TaskClassification,
    TripletexCredentials,
)


class TestSolveRequest:
    """Tests for the SolveRequest model."""

    def test_deserialize_minimal(self) -> None:
        """Minimal valid request with no files."""
        data = {
            "prompt": "Create an employee",
            "tripletex_credentials": {
                "base_url": "https://proxy.test/v2",
                "session_token": "tok123",
            },
        }
        req = SolveRequest(**data)
        assert req.prompt == "Create an employee"
        assert req.files == []
        assert req.tripletex_credentials.base_url == "https://proxy.test/v2"
        assert req.tripletex_credentials.session_token == "tok123"

    def test_deserialize_with_files(self) -> None:
        """Request with one file attachment."""
        data = {
            "prompt": "Registrer kvittering",
            "files": [
                {
                    "filename": "receipt.pdf",
                    "content_base64": "dGVzdA==",
                    "mime_type": "application/pdf",
                }
            ],
            "tripletex_credentials": {
                "base_url": "https://proxy.test/v2",
                "session_token": "tok",
            },
        }
        req = SolveRequest(**data)
        assert len(req.files) == 1
        assert req.files[0].filename == "receipt.pdf"
        assert req.files[0].mime_type == "application/pdf"

    def test_serialize_roundtrip(self) -> None:
        """Serialize to dict and back produces the same model."""
        req = SolveRequest(
            prompt="Test",
            tripletex_credentials=TripletexCredentials(
                base_url="https://proxy.test/v2",
                session_token="tok",
            ),
        )
        data = req.model_dump()
        restored = SolveRequest(**data)
        assert restored == req

    def test_missing_prompt_raises(self) -> None:
        """Missing required field 'prompt' raises ValidationError."""
        with pytest.raises(ValidationError):
            SolveRequest(
                tripletex_credentials=TripletexCredentials(
                    base_url="https://proxy.test/v2",
                    session_token="tok",
                ),
            )  # type: ignore[call-arg]

    def test_missing_credentials_raises(self) -> None:
        """Missing required field 'tripletex_credentials' raises."""
        with pytest.raises(ValidationError):
            SolveRequest(prompt="test")  # type: ignore[call-arg]

    def test_multiple_file_attachments(self) -> None:
        """Request with multiple files."""
        files = [
            FileAttachment(filename="a.pdf", content_base64="YQ==", mime_type="application/pdf"),
            FileAttachment(filename="b.png", content_base64="Yg==", mime_type="image/png"),
        ]
        req = SolveRequest(
            prompt="Test",
            files=files,
            tripletex_credentials=TripletexCredentials(
                base_url="https://proxy.test/v2",
                session_token="tok",
            ),
        )
        assert len(req.files) == 2
        assert req.files[1].filename == "b.png"


class TestSolveResponse:
    """Tests for the SolveResponse model."""

    def test_default_status(self) -> None:
        """Default status is 'completed'."""
        resp = SolveResponse()
        assert resp.status == "completed"

    def test_serialize_to_dict(self) -> None:
        """Serializes to expected JSON shape."""
        assert SolveResponse().model_dump() == {"status": "completed"}

    def test_custom_status(self) -> None:
        """Can override status if needed."""
        assert SolveResponse(status="failed").status == "failed"


class TestTaskClassification:
    """Tests for the TaskClassification model."""

    def test_full_classification(self) -> None:
        """All fields populated."""
        tc = TaskClassification(
            task_type="create_employee",
            params={"first_name": "Ola", "last_name": "Nordmann"},
            confidence=0.95,
        )
        assert tc.task_type == "create_employee"
        assert tc.params["first_name"] == "Ola"
        assert tc.confidence == 0.95

    def test_defaults(self) -> None:
        """Optional fields use defaults."""
        tc = TaskClassification(task_type="create_customer")
        assert tc.params == {}
        assert tc.confidence == 1.0

    def test_serialize_roundtrip(self) -> None:
        """Serialize and deserialize preserves data."""
        tc = TaskClassification(
            task_type="update_employee",
            params={"employee_id": 42, "email": "new@test.no"},
        )
        data = tc.model_dump()
        restored = TaskClassification(**data)
        assert restored.task_type == tc.task_type
        assert restored.params == tc.params


class TestFileAttachment:
    """Tests for the FileAttachment model."""

    def test_valid_attachment(self) -> None:
        """Create a valid file attachment."""
        fa = FileAttachment(
            filename="invoice.pdf",
            content_base64="dGVzdCBkYXRh",
            mime_type="application/pdf",
        )
        assert fa.filename == "invoice.pdf"
        assert fa.content_base64 == "dGVzdCBkYXRh"

    def test_missing_field_raises(self) -> None:
        """Missing required field raises."""
        with pytest.raises(ValidationError):
            FileAttachment(filename="test.pdf")  # type: ignore[call-arg]


class TestApiError:
    """Tests for the ApiError model."""

    def test_minimal_error(self) -> None:
        """Only status is required."""
        err = ApiError(status=404)
        assert err.status == 404
        assert err.message == ""
        assert err.validation_messages == []

    def test_full_error(self) -> None:
        """All fields populated."""
        err = ApiError(
            status=400,
            code=2001,
            message="Validation failed",
            developer_message="Field 'name' is required",
            validation_messages=[{"field": "name", "message": "Required"}],
            request_id="req-123",
        )
        assert err.code == 2001
        assert len(err.validation_messages) == 1
        assert err.request_id == "req-123"
