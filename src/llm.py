"""LLM integration for task classification and parameter extraction.

Uses Claude API to classify incoming prompts into task types
and extract structured parameters for handler execution.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import os

import anthropic

from src.constants import (
    ALL_TASK_TYPES,
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

SYSTEM_PROMPT = f"""You are a task classifier for Tripletex accounting software.
Given a user prompt (in any language), identify the task type and extract parameters.

TASK TYPES: {json.dumps(ALL_TASK_TYPES)}

CLASSIFICATION RULES (important!):
- If the task mentions creating an order AND an invoice (or "faktura"), classify as "create_invoice"
- If the task mentions creating an order/invoice AND registering payment, classify as "create_invoice" and include payment info in register_payment param
- If the task ONLY creates an order (no invoice), classify as "create_order"
- If the task mentions a customer by name, pass the full name as "customer" (string or object with "name")
- If the task mentions products by name/number, include them in orderLines with product name/number

PARAMETER SCHEMAS per task type:
- create_employee: {{firstName, lastName, email, phoneNumberMobile, userType ("STANDARD" or "ADMINISTRATOR")}}
- update_employee: {{firstName, lastName (to find), fields to update...}}
- create_customer: {{name, email, phoneNumber, organizationNumber, ...}}
- update_customer: {{name (to find), fields to update...}}
- create_product: {{name, number, priceExcludingVatCurrency, vatType, ...}}
- create_department: {{name, departmentNumber, departmentManager, ...}}
- create_project: {{name, number, startDate, endDate, customer, ...}}
- update_project: {{projectId or name (to find), fields to update...}}
- assign_role: {{firstName, lastName, role, ...}}
- enable_module: {{moduleName, ...}}
- create_order: {{customer, orderDate, deliveryDate, orderLines: [{{product: {{name, number}}, count, unitPriceExcludingVatCurrency}}]}}
- create_invoice: {{customer, invoiceDate, invoiceDueDate, orderLines: [{{product: {{name, number}}, count, unitPriceExcludingVatCurrency or amount}}], register_payment: {{amount, paymentDate}} (if payment mentioned)}}
- send_invoice: {{invoiceId or search criteria...}}
- register_payment: {{invoiceId or search criteria, amount, paymentDate, ...}}
- create_credit_note: {{invoiceId or search criteria, ...}}
- create_travel_expense: {{employee, project, travelDetails, costs, ...}}
- deliver_travel_expense: {{travelExpenseId or search criteria...}}
- approve_travel_expense: {{travelExpenseId or search criteria...}}
- link_project_customer: {{projectId, customer, ...}}
- create_activity: {{name, ...}}
- create_asset: {{name, ...}}
- update_asset: {{id/name (to find), fields to update...}}
- create_voucher: {{date, description, postings (debit/credit accounts, amounts), ...}}
- reverse_voucher: {{voucherId or search criteria...}}
- bank_reconciliation: {{account, date, ...}}
- ledger_correction: {{account, amount, date, description, ...}}
- year_end_closing: {{year, ...}}
- balance_sheet_report: {{dateFrom, dateTo, ...}}

Respond ONLY with valid JSON: {{"task_type": "<type>", "params": {{...}}}}
Extract ALL relevant parameters from the prompt. Use field names matching the Tripletex API.
If dates are mentioned, format as yyyy-MM-dd.
If the prompt references attached files, note that in params as "has_attachments": true."""


class LLMClient:
    """Client for LLM-based task classification and parameter extraction.

    Uses Vertex AI by default (set ANTHROPIC_VERTEX_PROJECT_ID env var).
    Falls back to direct Anthropic API if ANTHROPIC_API_KEY is set instead.
    """

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

    def classify_and_extract(
        self,
        prompt: str,
        files: list[FileAttachment] | None = None,
    ) -> TaskClassification:
        """Classify a prompt into a task type and extract parameters.

        Sends the prompt (and any file attachments) to Claude,
        then parses the structured JSON response.
        """
        messages = self._build_messages(prompt, files)

        for attempt in range(LLM_MAX_RETRIES + 1):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=LLM_MAX_TOKENS,
                    temperature=LLM_TEMPERATURE,
                    system=SYSTEM_PROMPT,
                    messages=messages,  # type: ignore[arg-type]
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

        # Should not reach here
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
                # Claude vision supports image types and PDFs
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
                    # Decode and include as text context
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
    def _parse_response(response: Any) -> TaskClassification:
        """Extract TaskClassification from the LLM response text."""
        text = response.content[0].text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON response: %.200s", text)
            return TaskClassification(task_type="unknown", params={})
        return TaskClassification(
            task_type=parsed.get("task_type", "unknown"),
            params=parsed.get("params", {}),
        )
