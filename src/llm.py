"""LLM integration for task classification and parameter extraction.

Uses Claude API to classify incoming prompts into task types
and extract structured parameters for handler execution.
Supports multi-step task decomposition for complex prompts.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import anthropic

from src.constants import (
    LLM_CLAUDE_MODEL,
    LLM_MAX_RETRIES,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    LLM_VERTEX_MODEL,
    LLM_VERTEX_PROJECT_ID,
    LLM_VERTEX_REGION,
)
from src.models import FileAttachment, TaskClassification

logger = logging.getLogger(__name__)

# Classification rules that are cross-cutting (not tied to any single handler).
_CLASSIFICATION_RULES = """\
CLASSIFICATION RULES (important!):
- If the task mentions creating an order AND an invoice (or "faktura"), classify as "create_invoice"
- If the task mentions creating an order/invoice AND registering payment, classify as \
"create_invoice" and include payment info in register_payment param
- If the task ONLY creates an order (no invoice), classify as "create_order"
- If the task mentions REVERSING a payment, returned payment, or "reversering av betaling", \
classify as "register_payment" with negative amount and "reversal": true. \
Include "orderLines" with the product/service name and amount from the original invoice.
- Do NOT classify payment reversals as "reverse_voucher" — use "register_payment" instead
- If the task mentions a customer by name, pass as "customer" object: \
{"name": "...", "organizationNumber": "..."} (include org number if mentioned)
- If the task mentions products by name/number, include them in orderLines with product name/number
- For SUPPLIERS (leverandør, supplier, Lieferant, fournisseur, proveedor, fornecedor), \
classify as "create_supplier" — NOT create_customer. \
Suppliers provide goods/services TO us; customers buy FROM us.
- If the task asks to create MULTIPLE entities of the same type (e.g. "create three departments"), \
extract ALL items in an "items" array. Example: {"task_type": "create_department", \
"params": {"items": [{"name": "Dept1"}, {"name": "Dept2"}]}}
- For supplier invoices (leverandørfaktura/Lieferantenrechnung), classify as "create_voucher"
- For payroll/salary tasks (lønn, paie, Gehalt, nómina, run payroll), classify as "run_payroll"
- For custom accounting dimensions (dimensjon, dimension, Dimension) with voucher, \
classify as "create_dimension_voucher"
- For logging hours/timesheet (timer, timeregistrering, log hours, Stunden erfassen, \
registrar horas), classify as "log_timesheet". If the task also asks to generate an \
invoice from the hours, still classify as "log_timesheet" with generateInvoice: true

MULTI-STEP TASKS:
- If the prompt asks for MULTIPLE DIFFERENT operations (e.g. "create a voucher AND send an \
invoice AND register a payment"), decompose into separate tasks in the "tasks" array.
- Order the tasks logically: create entities before referencing them, \
book vouchers before invoices, etc.
- Share context between steps: if step 1 creates a customer, use the same customer \
name/reference in later steps that need it.
- Common multi-step patterns:
  * "Book a fee + create an invoice for it + send it" → create_voucher, create_invoice, send_invoice
  * "Create invoice + register payment" → create_invoice (with register_payment in params)
  * "Find overdue invoice + register partial payment" → register_payment (searches automatically)
  * "Create employee + assign role" → create_employee, assign_role
  * PROJECT LIFECYCLE (budget + hours + supplier cost + invoice) → \
create_project, log_timesheet (per employee), create_voucher (supplier cost), create_invoice
- IMPORTANT: For project lifecycle tasks that mention registering hours, supplier costs, AND \
invoicing, you MUST decompose into the FULL workflow: create_project first, then log_timesheet \
for each employee, then create_voucher for supplier costs, then create_invoice. Do NOT just \
create entities — execute the complete workflow.

EFFICIENCY RULES:
- Only POST/PUT/DELETE/PATCH calls count for efficiency scoring. GET requests are FREE.
- Every 4xx error (400, 404, 422) reduces the efficiency bonus. Avoid trial-and-error.
- A fresh empty sandbox is created for each submission — entities must be created before use.

Extract ALL relevant parameters from the prompt. Use field names matching the Tripletex API.
If dates are mentioned, format as yyyy-MM-dd.
If the prompt references attached files, note that in params as "has_attachments": true."""


def build_system_prompt(handlers: dict[str, Any]) -> str:
    """Assemble the classification prompt from handler metadata."""
    all_task_types = sorted(handlers.keys())

    # Group handlers by tier
    tiers: dict[int, list[tuple[str, Any]]] = {1: [], 2: [], 3: []}
    for task_type in all_task_types:
        h = handlers[task_type]
        tier = getattr(h, "tier", 1)
        tiers.setdefault(tier, []).append((task_type, h))

    # Build parameter schemas section
    schema_lines = []
    for tier_num in sorted(tiers.keys()):
        tier_handlers = tiers[tier_num]
        if not tier_handlers:
            continue
        tier_labels = {1: "simple CRUD", 2: "multi-step", 3: "complex workflows"}
        schema_lines.append(
            f"\nTier {tier_num} ({tier_labels.get(tier_num, '')}, x{tier_num} multiplier):"
        )
        for task_type, h in tier_handlers:
            desc = getattr(h, "description", "") or ""
            param_schema = getattr(h, "param_schema", {}) or {}

            if param_schema:
                param_parts = []
                for pname, pspec in param_schema.items():
                    hint = pspec.description
                    req = "" if pspec.required else ", optional"
                    param_parts.append(f"{pname}{req}" + (f" ({hint})" if hint else ""))
                params_str = "{" + ", ".join(param_parts) + "}"
            else:
                params_str = "{...}"

            line = f"- {task_type}: {params_str}"
            if desc:
                line = f"- {task_type} — {desc}: {params_str}"
            schema_lines.append(line)

    # Collect disambiguation notes from handlers
    disambig_lines = []
    for task_type in all_task_types:
        h = handlers[task_type]
        disambig = getattr(h, "disambiguation", None)
        if disambig:
            disambig_lines.append(f"- {task_type}: {disambig}")

    # Assemble full prompt
    parts = [
        "You are a task classifier for Tripletex accounting software.",
        "Given a user prompt (in any language), identify the task type(s) and extract parameters.",
        "If the prompt requires MULTIPLE different operations, return them all in the tasks array.",
        "",
        f"TASK TYPES: {json.dumps(all_task_types)}",
        "",
        _CLASSIFICATION_RULES,
    ]

    if disambig_lines:
        parts.append("")
        parts.append("ADDITIONAL DISAMBIGUATION:")
        parts.extend(disambig_lines)

    parts.append("")
    parts.append("PARAMETER SCHEMAS per task type:")
    parts.extend(schema_lines)

    return "\n".join(parts)


class LLMClient:
    """Client for LLM-based task classification and parameter extraction."""

    def __init__(self, api_key: str | None = None) -> None:
        project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", LLM_VERTEX_PROJECT_ID)
        region = os.environ.get("CLOUD_ML_REGION", LLM_VERTEX_REGION)

        if project_id and not api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            self._client = anthropic.AnthropicVertex(
                project_id=project_id,
                region=region,
                timeout=LLM_TIMEOUT,
            )
            self._model = LLM_VERTEX_MODEL
            logger.info("Using Claude via Vertex AI (project=%s, region=%s)", project_id, region)
        else:
            self._client = anthropic.Anthropic(
                api_key=api_key,
                timeout=LLM_TIMEOUT,
            )
            self._model = LLM_CLAUDE_MODEL
            logger.info("Using Claude via direct Anthropic API")

        # Build system prompt from registered handlers
        from src.handlers import HANDLER_REGISTRY

        self._system_prompt = build_system_prompt(HANDLER_REGISTRY)
        self._all_task_types = sorted(HANDLER_REGISTRY.keys())

    def classify_and_extract(
        self,
        prompt: str,
        files: list[FileAttachment] | None = None,
    ) -> list[TaskClassification]:
        """Classify a prompt into one or more tasks with structured output.

        Returns a list of TaskClassification objects. Single-task prompts
        return a list with one element.
        """
        messages = self._build_messages(prompt, files)

        classify_tool = {
            "name": "classify_task",
            "description": "Classify the accounting task(s) and extract all parameters. "
            "For multi-step prompts, include all tasks in the tasks array.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "description": "Ordered list of tasks to execute. "
                        "Use a single item for simple prompts, multiple for multi-step.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "task_type": {
                                    "type": "string",
                                    "enum": self._all_task_types,
                                    "description": "The task type to execute",
                                },
                                "params": {
                                    "type": "object",
                                    "description": "Extracted parameters for the handler",
                                },
                            },
                            "required": ["task_type", "params"],
                        },
                    },
                },
                "required": ["tasks"],
            },
        }

        for attempt in range(LLM_MAX_RETRIES + 1):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=LLM_MAX_TOKENS,
                    temperature=LLM_TEMPERATURE,
                    system=self._system_prompt,
                    messages=messages,  # type: ignore[arg-type]
                    tools=[classify_tool],  # type: ignore[list-item]
                    tool_choice={"type": "tool", "name": "classify_task"},
                )
                return self._parse_response(response)
            except anthropic.APIStatusError as exc:
                if attempt < LLM_MAX_RETRIES and exc.status_code >= 500:
                    logger.warning("LLM transient error %d, retrying", exc.status_code)
                    continue
                raise
            except anthropic.APIConnectionError:
                if attempt < LLM_MAX_RETRIES:
                    logger.warning("LLM connection error, retrying")
                    continue
                raise

        raise RuntimeError("LLM retries exhausted")

    @staticmethod
    def _build_messages(
        prompt: str,
        files: list[FileAttachment] | None,
    ) -> list[dict[str, Any]]:
        """Build the messages array, including file attachments as images."""
        content: list[dict[str, Any]] = []

        if files:
            for f in files:
                media_type = f.mime_type
                if media_type.startswith("image/"):
                    content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": f.content_base64,
                            },
                        }
                    )
                elif media_type == "application/pdf":
                    content.append(
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": f.content_base64,
                            },
                        }
                    )
                else:
                    try:
                        text = base64.b64decode(f.content_base64).decode("utf-8", errors="replace")
                        content.append(
                            {
                                "type": "text",
                                "text": f"[File: {f.filename}]\n{text[:2000]}",
                            }
                        )
                    except Exception:
                        logger.warning("Could not decode file %s", f.filename)

        content.append({"type": "text", "text": prompt})
        return [{"role": "user", "content": content}]

    @staticmethod
    def _parse_response(response: Any) -> list[TaskClassification]:
        """Extract list of TaskClassification from tool_use response."""
        for block in response.content:
            if block.type == "tool_use" and block.name == "classify_task":
                parsed = block.input
                tasks = parsed.get("tasks", [])
                if tasks:
                    return [
                        TaskClassification(
                            task_type=t.get("task_type", "unknown"),
                            params=t.get("params", {}),
                        )
                        for t in tasks
                    ]
                # Fallback: old single-task format
                if "task_type" in parsed:
                    return [
                        TaskClassification(
                            task_type=parsed.get("task_type", "unknown"),
                            params=parsed.get("params", {}),
                        )
                    ]

        # Fallback: parse text response
        for block in response.content:
            if block.type == "text":
                text = block.text.strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return [
                            TaskClassification(
                                task_type=t.get("task_type", "unknown"),
                                params=t.get("params", {}),
                            )
                            for t in parsed
                            if isinstance(t, dict)
                        ]
                    if isinstance(parsed, dict):
                        return [
                            TaskClassification(
                                task_type=parsed.get("task_type", "unknown"),
                                params=parsed.get("params", {}),
                            )
                        ]
                except json.JSONDecodeError:
                    logger.warning("LLM text fallback non-JSON: %.200s", text)

        logger.warning("No tool_use or parseable text in LLM response")
        return [TaskClassification(task_type="unknown", params={})]
