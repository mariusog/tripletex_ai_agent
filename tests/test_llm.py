"""Tests for the LLM integration module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.llm import LLMClient
from src.models import FileAttachment, TaskClassification


@pytest.fixture
def llm_client() -> LLMClient:
    """Create an LLMClient with a mocked Anthropic client."""
    with patch("src.llm.anthropic.Anthropic"):
        client = LLMClient(api_key="test-key")
    return client


def _make_response(text: str) -> MagicMock:
    """Build a mock Claude API response with tool_use content.

    Accepts a JSON string, parses it, and returns a mock response
    with a tool_use block (matching the tool_use structured output flow).
    """
    parsed = json.loads(text)
    block = MagicMock()
    block.type = "tool_use"
    block.name = "classify_task"
    block.input = parsed
    response = MagicMock()
    response.content = [block]
    return response


def _make_text_response(text: str) -> MagicMock:
    """Build a mock Claude API response with text content (fallback path)."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


class TestClassifyAndExtract:
    """Tests for the classify_and_extract method."""

    def test_basic_classification(self, llm_client: LLMClient) -> None:
        response_text = json.dumps(
            {
                "task_type": "create_employee",
                "params": {"firstName": "John", "lastName": "Doe"},
            }
        )
        mock_resp = _make_response(response_text)
        llm_client._client.messages.create = MagicMock(return_value=mock_resp)

        result = llm_client.classify_and_extract("Create employee John Doe")
        assert isinstance(result, TaskClassification)
        assert result.task_type == "create_employee"
        assert result.params["firstName"] == "John"

    def test_handles_markdown_code_fences(self, llm_client: LLMClient) -> None:
        """Test fallback text parsing when tool_use is not returned."""
        inner = json.dumps({"task_type": "create_customer", "params": {}})
        response_text = f"```json\n{inner}\n```"
        mock_resp = _make_text_response(response_text)
        llm_client._client.messages.create = MagicMock(return_value=mock_resp)

        result = llm_client.classify_and_extract("Create a new customer")
        assert result.task_type == "create_customer"

    def test_unknown_task_type(self, llm_client: LLMClient) -> None:
        response_text = json.dumps({"task_type": "unknown", "params": {}})
        mock_resp = _make_response(response_text)
        llm_client._client.messages.create = MagicMock(return_value=mock_resp)

        result = llm_client.classify_and_extract("Do something weird")
        assert result.task_type == "unknown"

    def test_missing_task_type_defaults_unknown(self, llm_client: LLMClient) -> None:
        response_text = json.dumps({"params": {"name": "Test"}})
        mock_resp = _make_response(response_text)
        llm_client._client.messages.create = MagicMock(return_value=mock_resp)

        result = llm_client.classify_and_extract("Some prompt")
        assert result.task_type == "unknown"


class TestBuildMessages:
    """Tests for message construction with file attachments."""

    def test_text_only_message(self) -> None:
        messages = LLMClient._build_messages("Hello", None)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        content = messages[0]["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Hello"

    def test_image_attachment(self) -> None:
        files = [
            FileAttachment(
                filename="receipt.png",
                content_base64="aW1hZ2VkYXRh",
                mime_type="image/png",
            )
        ]
        messages = LLMClient._build_messages("Process this", files)
        content = messages[0]["content"]
        assert len(content) == 2
        assert content[0]["type"] == "image"
        assert content[0]["source"]["media_type"] == "image/png"
        assert content[1]["type"] == "text"

    def test_pdf_attachment(self) -> None:
        files = [
            FileAttachment(
                filename="doc.pdf",
                content_base64="cGRmZGF0YQ==",
                mime_type="application/pdf",
            )
        ]
        messages = LLMClient._build_messages("Process this", files)
        content = messages[0]["content"]
        assert content[0]["type"] == "document"
        assert content[0]["source"]["media_type"] == "application/pdf"

    def test_text_file_attachment(self) -> None:
        import base64

        text_data = base64.b64encode(b"Hello world").decode()
        files = [
            FileAttachment(
                filename="data.txt",
                content_base64=text_data,
                mime_type="text/plain",
            )
        ]
        messages = LLMClient._build_messages("Process this", files)
        content = messages[0]["content"]
        assert content[0]["type"] == "text"
        assert "Hello world" in content[0]["text"]


class TestRetryBehavior:
    """Tests for transient error retry logic."""

    def test_retries_on_500(self, llm_client: LLMClient) -> None:
        import anthropic

        success_resp = _make_response(json.dumps({"task_type": "create_employee", "params": {}}))
        error = anthropic.APIStatusError(
            message="Server Error",
            response=MagicMock(status_code=500),
            body=None,
        )
        llm_client._client.messages.create = MagicMock(side_effect=[error, success_resp])
        result = llm_client.classify_and_extract("test")
        assert result.task_type == "create_employee"

    def test_no_retry_on_400(self, llm_client: LLMClient) -> None:
        import anthropic

        error = anthropic.APIStatusError(
            message="Bad Request",
            response=MagicMock(status_code=400),
            body=None,
        )
        llm_client._client.messages.create = MagicMock(side_effect=error)
        with pytest.raises(anthropic.APIStatusError):
            llm_client.classify_and_extract("test")
        assert llm_client._client.messages.create.call_count == 1

    def test_retries_on_connection_error(self, llm_client: LLMClient) -> None:
        import anthropic

        success = _make_response(json.dumps({"task_type": "create_employee", "params": {}}))
        conn_err = anthropic.APIConnectionError(request=MagicMock())
        llm_client._client.messages.create = MagicMock(side_effect=[conn_err, success])
        result = llm_client.classify_and_extract("test")
        assert result.task_type == "create_employee"


class TestNorwegianAndTimeout:
    """Tests for Norwegian prompts and timeout handling."""

    def test_handles_norwegian_prompt(self, llm_client: LLMClient) -> None:
        response_text = json.dumps(
            {
                "task_type": "create_employee",
                "params": {"firstName": "Ola", "lastName": "Nordmann"},
            }
        )
        mock_resp = _make_response(response_text)
        llm_client._client.messages.create = MagicMock(return_value=mock_resp)

        result = llm_client.classify_and_extract("Opprett en ny ansatt med navn Ola Nordmann")
        assert result.task_type == "create_employee"
        assert result.params["firstName"] == "Ola"

    def test_timeout_raises_error(self, llm_client: LLMClient) -> None:
        import anthropic

        timeout_err = anthropic.APITimeoutError(request=MagicMock())
        llm_client._client.messages.create = MagicMock(side_effect=timeout_err)
        with pytest.raises(anthropic.APITimeoutError):
            llm_client.classify_and_extract("test")
