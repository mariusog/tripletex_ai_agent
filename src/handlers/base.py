"""Base handler class and registration decorator for Tripletex task handlers.

All task handlers inherit from BaseHandler and register via @register_handler.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from src.api_client import TripletexClient

logger = logging.getLogger(__name__)

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class BaseHandler(ABC):
    """Abstract base class for all Tripletex task handlers.

    Each handler maps to one task_type and executes the minimum
    API calls needed to complete the task.
    """

    @abstractmethod
    def get_task_type(self) -> str:
        """Return the task_type string this handler processes."""

    @property
    @abstractmethod
    def required_params(self) -> list[str]:
        """Parameter names that must be present in params dict."""

    @abstractmethod
    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        """Execute the task using the Tripletex API.

        Args:
            api_client: Authenticated Tripletex API client.
            params: Extracted parameters from the LLM classification.

        Returns:
            Dict with result details (e.g., created entity ID).
        """

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Check that all required params are present. Returns missing names."""
        return [p for p in self.required_params if p not in params]

    @staticmethod
    def ensure_ref(value: Any, field_name: str = "") -> dict[str, Any]:
        """Convert int or dict to Tripletex object reference {"id": N}.

        Safely handles int, str-of-int, and dict inputs.
        Logs a warning for unexpected types.
        """
        if isinstance(value, dict):
            if "id" in value:
                return value
            logger.warning("Object ref for '%s' missing 'id': %s", field_name, value)
            return value
        try:
            return {"id": int(value)}
        except (TypeError, ValueError):
            logger.warning("Cannot convert '%s' to ref for '%s'", value, field_name)
            return {"id": 0}

    @staticmethod
    def validate_date(value: Any, field_name: str = "") -> str | None:
        """Validate and return a yyyy-MM-dd date string, or None if invalid."""
        if value is None:
            return None
        s = str(value).strip()[:10]
        if DATE_PATTERN.match(s):
            return s
        logger.warning("Invalid date for '%s': '%s' (expected yyyy-MM-dd)", field_name, value)
        return None

    @staticmethod
    def safe_int(value: Any, field_name: str = "", default: int = 0) -> int:
        """Safely convert a value to int with logging on failure."""
        try:
            return int(value)
        except (TypeError, ValueError):
            logger.warning("Cannot convert '%s' to int for '%s'", value, field_name)
            return default

    @staticmethod
    def strip_none_values(data: dict[str, Any]) -> dict[str, Any]:
        """Remove keys with None values from a payload dict."""
        return {k: v for k, v in data.items() if v is not None}


# Global registry populated by @register_handler
HANDLER_REGISTRY: dict[str, BaseHandler] = {}


def register_handler(cls: type[BaseHandler]) -> type[BaseHandler]:
    """Class decorator that instantiates a handler and registers it."""
    instance = cls()
    task_type = instance.get_task_type()
    HANDLER_REGISTRY[task_type] = instance
    logger.debug("Registered handler for task_type=%s", task_type)
    return cls


def get_handler(task_type: str) -> BaseHandler | None:
    """Look up a handler by task_type. Returns None if not found."""
    return HANDLER_REGISTRY.get(task_type)
