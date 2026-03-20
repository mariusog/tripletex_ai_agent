"""Tests for handler base class and registry."""

from __future__ import annotations

from typing import Any

import pytest

from src.handlers.base import HANDLER_REGISTRY, BaseHandler, get_handler, register_handler


class TestBaseHandlerContract:
    """Verify BaseHandler ABC enforces the contract."""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BaseHandler()  # type: ignore[abstract]


class TestHandlerRegistry:
    """Verify the handler registry and decorator."""

    def test_register_handler_decorator(self):
        @register_handler
        class _DummyHandler(BaseHandler):
            def get_task_type(self) -> str:
                return "__test_dummy__"

            @property
            def required_params(self) -> list[str]:
                return ["x"]

            def execute(self, api_client: Any, params: dict[str, Any]) -> dict[str, Any]:
                return {}

        assert "__test_dummy__" in HANDLER_REGISTRY
        handler = get_handler("__test_dummy__")
        assert handler is not None
        assert handler.get_task_type() == "__test_dummy__"
        del HANDLER_REGISTRY["__test_dummy__"]

    def test_get_handler_missing_returns_none(self):
        assert get_handler("__nonexistent__") is None
