"""Pydantic models for the Tripletex AI Agent.

Defines request/response shapes for the POST /solve endpoint
and internal data structures for task routing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FileAttachment(BaseModel):
    """A file attached to the solve request (PDF receipt, image, etc.)."""

    filename: str
    content_base64: str
    mime_type: str


class TripletexCredentials(BaseModel):
    """Credentials for authenticating with the Tripletex API proxy."""

    base_url: str
    session_token: str


class SolveRequest(BaseModel):
    """Incoming request to the POST /solve endpoint."""

    prompt: str
    files: list[FileAttachment] = Field(default_factory=list)
    tripletex_credentials: TripletexCredentials


class SolveResponse(BaseModel):
    """Response from the POST /solve endpoint. Always returns completed."""

    status: str = "completed"


class TaskClassification(BaseModel):
    """Result of LLM classifying a prompt into a task type with parameters."""

    task_type: str
    params: dict[str, object] = Field(default_factory=dict)
    confidence: float = 1.0


class ApiError(BaseModel):
    """Parsed Tripletex API error response."""

    status: int
    code: int = 0
    message: str = ""
    developer_message: str = ""
    validation_messages: list[dict[str, Any]] = Field(default_factory=list)
    request_id: str = ""
