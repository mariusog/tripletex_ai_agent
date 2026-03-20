"""Central task router that connects LLM classification to handler execution.

Orchestrates the flow: parse request -> classify via LLM -> lookup handler -> execute.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.api_client import TripletexClient
from src.handlers import HANDLER_REGISTRY
from src.llm import LLMClient
from src.models import SolveRequest, SolveResponse, TaskClassification

logger = logging.getLogger(__name__)


class TaskRouter:
    """Routes classified tasks to the correct handler and executes them."""

    def __init__(
        self,
        llm_client: LLMClient,
        handler_registry: dict[str, Any] | None = None,
    ) -> None:
        self._llm = llm_client
        self._registry = handler_registry or HANDLER_REGISTRY

    async def solve(self, request: SolveRequest) -> SolveResponse:
        """Parse request, classify via LLM, execute handler, return response."""
        start = time.monotonic()
        api_client = TripletexClient(
            base_url=request.tripletex_credentials.base_url,
            session_token=request.tripletex_credentials.session_token,
        )

        try:
            classification = self._classify(request)
            task_type = classification.task_type
            params = classification.params
            logger.info("Classified as task_type=%s params=%s", task_type, params)

            handler = self._registry.get(task_type)
            if handler is None:
                logger.warning("No handler for task_type=%s, skipping execution", task_type)
                return SolveResponse(status="completed")

            missing = handler.validate_params(params)
            if missing:
                logger.warning(
                    "Missing params %s for task_type=%s, executing anyway",
                    missing,
                    task_type,
                )

            result = handler.execute(api_client, params)
            elapsed = time.monotonic() - start
            logger.info(
                "Handler result task_type=%s handler=%s api_calls=%d duration=%.2fs result=%s",
                task_type,
                type(handler).__name__,
                api_client.api_call_count,
                elapsed,
                result,
            )
        except Exception:
            elapsed = time.monotonic() - start
            logger.exception("Router error after %.2fs", elapsed)
        finally:
            api_client.close()

        return SolveResponse(status="completed")

    def _classify(self, request: SolveRequest) -> TaskClassification:
        """Classify via LLM with one retry on failure."""
        try:
            return self._llm.classify_and_extract(
                prompt=request.prompt,
                files=request.files or None,
            )
        except Exception:
            logger.warning("LLM classification failed, retrying with rephrased prompt")

        rephrased = (
            f"Identify the Tripletex accounting task in this request "
            f"and extract parameters:\n\n{request.prompt}"
        )
        return self._llm.classify_and_extract(prompt=rephrased, files=request.files or None)


def create_router() -> TaskRouter:
    """Factory that creates a TaskRouter with default dependencies."""
    llm_client = LLMClient()
    return TaskRouter(llm_client=llm_client)
