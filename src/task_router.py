"""Central task router that connects LLM classification to handler execution.

Orchestrates the flow: parse request -> classify via LLM -> lookup handler(s) -> execute.
Supports multi-step task execution with shared context between steps.
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

_PLACEHOLDER_VALUES = {"<UNKNOWN>", "UNKNOWN", "unknown", "<unknown>", "TBD", "N/A", "n/a", ""}


def _strip_placeholders(params: dict) -> dict:
    """Remove params with placeholder values the LLM couldn't extract."""
    cleaned = {}
    for k, v in params.items():
        if isinstance(v, str) and v.strip() in _PLACEHOLDER_VALUES:
            continue
        if isinstance(v, dict):
            v = _strip_placeholders(v)
        cleaned[k] = v
    return cleaned


def _inject_context(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Inject shared context from previous steps into params.

    Context carries forward: customer refs, invoice IDs, etc.
    Only fills in missing params — never overwrites explicit values.
    """
    merged = dict(params)

    # If this step needs a customer and doesn't have one, use context
    if "customer" not in merged and "customer" in context:
        merged["customer"] = context["customer"]

    # If this step needs an invoiceId and doesn't have one, use context
    if "invoiceId" not in merged and "invoiceId" in context:
        merged["invoiceId"] = context["invoiceId"]

    # If this step needs an employee and doesn't have one, use context
    if "employee" not in merged and "employee" in context:
        merged["employee"] = context["employee"]

    return merged


def _update_context(
    context: dict[str, Any], result: dict[str, Any], params: dict[str, Any]
) -> None:
    """Update shared context with results from a completed step."""
    if result.get("id"):
        # Store the last created entity ID
        context["lastId"] = result["id"]

    # Propagate specific entity references
    if "customer" in params:
        context["customer"] = params["customer"]
    if result.get("id") and result.get("action") in ("created", "sent"):
        context["invoiceId"] = result["id"]
    if result.get("orderId"):
        context["orderId"] = result["orderId"]


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
        """Parse request, classify via LLM, execute handler(s), return response."""
        start = time.monotonic()
        api_client = TripletexClient(
            base_url=request.tripletex_credentials.base_url,
            session_token=request.tripletex_credentials.session_token,
        )

        try:
            classifications = self._classify(request)
            logger.info(
                "Classified %d task(s): %s",
                len(classifications),
                [c.task_type for c in classifications],
            )

            # Shared context carries entity refs between steps
            context: dict[str, Any] = {}

            for i, classification in enumerate(classifications):
                task_type = classification.task_type
                params = _strip_placeholders(classification.params)

                # Inject context from previous steps
                if i > 0:
                    params = _inject_context(params, context)

                logger.info(
                    "Step %d/%d: task_type=%s params=%s",
                    i + 1,
                    len(classifications),
                    task_type,
                    params,
                )

                handler = self._registry.get(task_type)
                if handler is None:
                    logger.warning("No handler for task_type=%s, skipping", task_type)
                    continue

                missing = handler.validate_params(params)
                if missing:
                    logger.warning(
                        "Missing params %s for task_type=%s, executing anyway",
                        missing,
                        task_type,
                    )

                # Handle batch "items" for handlers without native support
                try:
                    items = params.get("items", [])
                    if items and not hasattr(handler, "_create_one"):
                        results = []
                        for item in items:
                            merged = {**params, **item}
                            merged.pop("items", None)
                            results.append(handler.execute(api_client, merged))
                        result = {"results": results, "count": len(results)}
                    else:
                        result = handler.execute(api_client, params)

                    # Update context for next step
                    _update_context(context, result, params)

                    elapsed = time.monotonic() - start
                    logger.info(
                        "Handler result step=%d task_type=%s handler=%s "
                        "api_calls=%d writes=%d errors=%d duration=%.2fs result=%s",
                        i + 1,
                        task_type,
                        type(handler).__name__,
                        api_client.api_call_count,
                        api_client.write_call_count,
                        api_client.error_count,
                        elapsed,
                        result,
                    )
                except Exception:
                    elapsed = time.monotonic() - start
                    logger.exception(
                        "Step %d/%d failed (task_type=%s) after %.2fs, continuing",
                        i + 1,
                        len(classifications),
                        task_type,
                        elapsed,
                    )

        except Exception:
            elapsed = time.monotonic() - start
            logger.exception("Router error after %.2fs", elapsed)
        finally:
            api_client.close()

        return SolveResponse(status="completed")

    def _classify(self, request: SolveRequest) -> list[TaskClassification]:
        """Classify via LLM with one retry on failure."""
        try:
            return self._llm.classify_and_extract(
                prompt=request.prompt,
                files=request.files or None,
            )
        except Exception:
            logger.exception("LLM classification failed, retrying with rephrased prompt")

        rephrased = (
            f"Identify the Tripletex accounting task(s) in this request "
            f"and extract parameters:\n\n{request.prompt}"
        )
        return self._llm.classify_and_extract(prompt=rephrased, files=request.files or None)


def create_router() -> TaskRouter:
    """Factory that creates a TaskRouter with default dependencies."""
    llm_client = LLMClient()
    return TaskRouter(llm_client=llm_client)
