"""LLM integration for task classification and parameter extraction.

Uses Claude API to classify incoming prompts into task types
and extract structured parameters for handler execution.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

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
Given a user prompt (in any of 7 languages: Norwegian bokmål, Norwegian nynorsk, English, \
Spanish, Portuguese, German, French), identify the task type and extract parameters.

TASK TYPES: {json.dumps(ALL_TASK_TYPES)}

MULTILINGUAL KEYWORDS:
- faktura/invoice/factura/Rechnung/facture = invoice
- bestilling/ordre/order/Bestellung/commande = order
- ansatt/employee/Mitarbeiter/empleado/empregado/employé = employee
- kunde/customer/Kunde/cliente/client = customer
- produkt/product/Produkt/producto/produit = product
- reiseregning/reiseutgift/travel expense/Reisekostenabrechnung/gastos de viaje = travel expense
- bilag/voucher/Beleg/comprobante/pièce comptable = voucher
- leverandørfaktura/supplier invoice/Lieferantenrechnung = create_voucher (NOT create_invoice)
- kreditnota/credit note/Gutschrift/nota de crédito = credit note
- betaling/payment/Zahlung/pago/paiement = payment
- stornieren/Stornierung/zurückgebucht/Rückbuchung = payment reversal
- slett/slette/delete/löschen/eliminar/supprimer = delete
- avdeling/department/Abteilung/departamento = department
- prosjekt/project/Projekt/proyecto/projet = project
- årsoppgjør/årsavslutning/year-end closing/Jahresabschluss = year_end_closing
- bankavstemming/bank reconciliation/Bankabstimmung = bank_reconciliation

CLASSIFICATION RULES (important!):
- If the task mentions creating an order AND an invoice (or "faktura"), classify as "create_invoice"
- If the task mentions creating an order/invoice AND registering payment, classify as \
"create_invoice" and include payment info in register_payment param
- If the task ONLY creates an order (no invoice), classify as "create_order"
- If the task mentions REVERSING a payment, returned payment, or "reversering av betaling", \
classify as "register_payment" with negative amount and "reversal": true. \
Include "orderLines" with the product/service name and amount from the original invoice.
- Do NOT classify payment reversals as "reverse_voucher" — use "register_payment" instead
- If the task mentions DELETING a travel expense (slett reiseregning), classify as \
"delete_travel_expense"
- If the task mentions DELETING a voucher/entry (slett bilag), classify as "delete_voucher"
- If the task mentions creating a custom accounting DIMENSION and posting a voucher, \
classify as "create_voucher" with customDimension params (NOT a separate task type)
- If the task mentions booking a reminder fee (Mahngebühr/purregebyr/late fee) \
or finding an overdue invoice, classify as "create_voucher" with the fee postings
- If the task mentions reviewing/auditing the ledger and finding/fixing errors, \
classify as "ledger_correction"
- If the task mentions running payroll/salary (Gehaltsabrechnung/lønn/nómina), \
classify as "create_voucher" with salary account postings (debit 5000, credit 2920)
- If the task asks to create MULTIPLE entities (e.g., "three departments", "deux produits"), \
extract ALL names into a list param (e.g., departments: ["A", "B", "C"])
- If the task mentions a customer by name, pass the full name as "customer" \
(string or object with "name")
- If the task mentions products by name/number, include them in orderLines with product name/number
- For supplier invoices (leverandørfaktura/Lieferantenrechnung), classify as "create_voucher"
- If the task says "register/create supplier" (leverandør/fornecedor/proveedor/Lieferant), \
classify as "create_supplier" (NOT create_customer)

PARAMETER SCHEMAS per task type:
- create_employee: {{firstName, lastName, email, phoneNumberMobile, \
userType ("STANDARD" or "ADMINISTRATOR")}}
- update_employee: {{firstName, lastName (to find), fields to update...}}
- create_customer: {{name, email, phoneNumber, organizationNumber, \
postalAddress: {{addressLine1, postalCode, city}}, isSupplier (if mentioned as supplier), ...}}
- update_customer: {{name (to find), postalAddress: {{addressLine1, postalCode, city}}, \
fields to update...}}
- create_supplier: {{name, email, phoneNumber, organizationNumber, \
postalAddress: {{addressLine1, postalCode, city}}, ...}}
- create_product: {{name, number, priceExcludingVatCurrency, vatType, ...}}
- create_department: {{name (first department name), departmentNumber, departmentManager, \
departments: ["Name1", "Name2", "Name3"] (REQUIRED if prompt mentions multiple departments — \
extract ALL department names as a list)}}
- create_project: {{name, number, startDate, endDate, customer, ...}}
- update_project: {{projectId or name (to find), fixedPrice, \
invoicePercentage (if "invoice X% of fixed price" is mentioned), fields to update...}}
- assign_role: {{firstName, lastName, role, ...}}
- enable_module: {{moduleName, ...}}
- create_order: {{customer, orderDate, deliveryDate, \
orderLines: [{{product: {{name, number}}, count, unitPriceExcludingVatCurrency}}]}}
- create_invoice: {{customer, invoiceDate, invoiceDueDate, \
orderLines: [{{product: {{name, number}}, count, unitPriceExcludingVatCurrency or amount}}], \
register_payment: {{amount, paymentDate}} (if payment mentioned), \
send_invoice: true (if the prompt asks to SEND the invoice)}}
- send_invoice: {{invoiceId or search criteria...}}
- register_payment: {{customer, amount, paymentDate, description, reversal (bool), \
orderLines: [{{product: {{name, number}}, count, unitPriceExcludingVatCurrency}}]}}
- create_credit_note: {{invoiceId or search criteria, ...}}
- create_travel_expense: {{employee, project, travelDetails, costs, ...}}
- deliver_travel_expense: {{travelExpenseId or search criteria...}}
- approve_travel_expense: {{travelExpenseId or search criteria...}}
- link_project_customer: {{projectId, customer, ...}}
- create_activity: {{name, ...}}
- create_asset: {{name, ...}}
- update_asset: {{id/name (to find), fields to update...}}
- log_timesheet: {{employee, project, activity, hours, date, hourlyRate, \
comment, customer, createInvoice: true (if prompt asks to invoice)}}
- create_voucher: {{date, description, postings (debit/credit accounts, amounts), \
customDimension: {{name, values, linkedValue}} (if creating dimension), ...}}
- reverse_voucher: {{voucherId or search criteria...}}
- bank_reconciliation: {{account, date, ...}}
- ledger_correction: {{date, description, postings (correction entries), \
supplier (if AP accounts involved), corrections: [{{type, wrongAccount, \
correctAccount, amount, description}}] (list of errors to fix)}}
- year_end_closing: {{year, ...}}
- delete_travel_expense: {{travelExpenseId, employee (name to search), title (to match)}}
- delete_voucher: {{voucherId, number, date, description (to match)}}
- balance_sheet_report: {{dateFrom, dateTo, ...}}

EXAMPLES:
- "Créez trois départements: X, Y et Z" → create_department with \
departments: ["X","Y","Z"]
- "Create order + invoice + payment" → create_invoice with \
register_payment param
- "Reversed/returned payment" → register_payment with reversal: true
- "Create project X linked to customer Y" → create_project (NOT create_customer)

Extract ALL relevant parameters from the prompt. Use field names \
matching the Tripletex API.
If dates are mentioned, format as yyyy-MM-dd.
If a date is NOT mentioned in the prompt, OMIT the field entirely. \
Never output placeholder values like "<UNKNOWN>", "unknown", "TBD", or "N/A". \
Only include fields you can actually extract from the prompt.
If the prompt references attached files, note that in params as "has_attachments": true."""

# Tool definition for structured output — forces valid JSON with constrained task_type
CLASSIFY_TOOL = {
    "name": "classify_task",
    "description": "Classify the accounting task and extract all parameters from the prompt.",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_type": {
                "type": "string",
                "enum": ALL_TASK_TYPES,
                "description": "The task type to execute",
            },
            "params": {
                "type": "object",
                "description": "Extracted parameters for the task handler",
            },
        },
        "required": ["task_type", "params"],
    },
}


class LLMClient:
    """Client for LLM-based task classification and parameter extraction.

    Uses Vertex AI by default (set ANTHROPIC_VERTEX_PROJECT_ID env var).
    Falls back to direct Anthropic API if ANTHROPIC_API_KEY is set instead.
    Uses tool_use for guaranteed structured output.
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
            self._model = os.environ.get("LLM_MODEL_OVERRIDE", LLM_VERTEX_MODEL)
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

        Uses tool_use for guaranteed structured output — task_type is
        constrained to the enum of known types, eliminating JSON parse
        failures and invalid task types entirely.
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
                    tools=[CLASSIFY_TOOL],  # type: ignore[list-item]
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
        """Extract TaskClassification from tool_use response.

        With tool_use, Claude returns structured input directly —
        no JSON parsing needed. Falls back to text parsing if
        the response unexpectedly contains text instead.
        """
        for block in response.content:
            if block.type == "tool_use" and block.name == "classify_task":
                parsed = block.input
                return TaskClassification(
                    task_type=parsed.get("task_type", "unknown"),
                    params=parsed.get("params", {}),
                )

        # Fallback: parse text response (shouldn't happen with tool_choice)
        for block in response.content:
            if block.type == "text":
                text = block.text.strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        parsed = parsed[0] if parsed else {}
                    if isinstance(parsed, dict):
                        return TaskClassification(
                            task_type=parsed.get("task_type", "unknown"),
                            params=parsed.get("params", {}),
                        )
                except json.JSONDecodeError:
                    logger.warning("LLM text fallback non-JSON: %.200s", text)

        logger.warning("No tool_use or parseable text in LLM response")
        return TaskClassification(task_type="unknown", params={})
