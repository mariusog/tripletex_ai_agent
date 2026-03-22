"""Invoice workflow orchestration: order -> lines -> invoice -> payment.

Stateless service functions that handlers call. No handler imports another handler.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.api_helpers import ensure_bank_account
from src.handlers.entity_resolver import resolve as _resolve
from src.services.order_line_builder import build_and_post_order_lines

logger = logging.getLogger(__name__)


@dataclass
class InvoiceResult:
    """Result of the full invoice creation flow."""

    order_id: int | None = None
    invoice_id: int | None = None
    payment_registered: bool = False


def _maybe_create_project(
    api_client: TripletexClient,
    project: Any,
    customer_ref: dict[str, int],
    today: str,
) -> dict[str, int] | None:
    """Create a project if specified in params. Returns project ref or None."""
    if not project:
        return None
    proj_name = project.get("name") if isinstance(project, dict) else str(project)
    if not proj_name:
        return None
    emp_search = api_client.get_cached(
        "account_owner", "/employee", params={"count": 1}, fields="id"
    )
    emp_values = emp_search.get("values", [])
    pm_ref = {"id": emp_values[0]["id"]} if emp_values else {"id": 0}

    pm_info = project.get("projectManager") if isinstance(project, dict) else None
    if pm_info and isinstance(pm_info, dict) and "id" not in pm_info:
        _resolve(api_client, "employee", pm_info)

    proj_num = (
        str(project.get("number"))
        if isinstance(project, dict) and project.get("number")
        else str(secrets.randbelow(90000) + 10000)
    )
    proj_body: dict[str, Any] = {
        "name": proj_name,
        "number": proj_num,
        "projectManager": pm_ref,
        "startDate": today,
        "customer": customer_ref,
    }
    try:
        proj_result = api_client.post("/project", data=proj_body)
        proj_id = proj_result.get("value", {}).get("id")
        logger.info("Created project id=%s", proj_id)
        return {"id": proj_id}
    except TripletexApiError as e:
        logger.warning("Project creation failed: %s", e)
        return None


def _register_payment_on_invoice(
    api_client: TripletexClient,
    invoice_id: int,
    payment_date: str | None = None,
    amount_override: float | None = None,
) -> bool:
    """Register payment on an invoice.

    Uses amount_override if provided (e.g. for partial/currency payments),
    otherwise pays the full invoice amount.
    """
    try:
        if amount_override is not None:
            pay_amount = amount_override
        else:
            inv_data = api_client.get(f"/invoice/{invoice_id}", fields="amount")
            pay_amount = inv_data.get("value", {}).get("amount")
        if not pay_amount:
            return False
        pt_resp = api_client.get_cached(
            "invoice_payment_type",
            "/invoice/paymentType",
            params={"count": 1},
            fields="id",
        )
        pt_values = pt_resp.get("values", [])
        if not pt_values:
            return False
        api_client.put(
            f"/invoice/{invoice_id}/:payment",
            params={
                "paymentDate": payment_date or dt_date.today().isoformat(),
                "paymentTypeId": pt_values[0]["id"],
                "paidAmount": pay_amount,
            },
        )
        logger.info("Registered payment %s on invoice %s", pay_amount, invoice_id)
        return True
    except TripletexApiError as e:
        logger.warning("Payment failed: %s", e)
        return False


def create_full_invoice(
    api_client: TripletexClient,
    params: dict[str, Any],
) -> InvoiceResult:
    """Full flow: resolve entities -> order -> lines -> invoice -> optional payment."""
    today = dt_date.today().isoformat()
    result = InvoiceResult()

    # Step 0: Ensure bank account
    ensure_bank_account(api_client)

    # Step 1: Resolve customer
    cust_param = params.get("customer")
    if isinstance(cust_param, str) and params.get("organizationNumber"):
        cust_param = {"name": cust_param, "organizationNumber": params["organizationNumber"]}
    customer_ref = _resolve(api_client, "customer", cust_param)

    # Step 1b: Use existing projectId from context, or create project
    project_ref = None
    if params.get("projectId"):
        project_ref = {"id": int(params["projectId"])}
    elif params.get("project"):
        project_ref = _maybe_create_project(api_client, params["project"], customer_ref, today)

    # Step 2: Create order
    order_body: dict[str, Any] = {
        "customer": customer_ref,
        "orderDate": params.get("orderDate") or today,
        "deliveryDate": params.get("deliveryDate") or today,
    }
    if project_ref:
        order_body["project"] = project_ref
    order_body = {k: v for k, v in order_body.items() if v is not None}
    order_result = api_client.post("/order", data=order_body)
    result.order_id = order_result.get("value", {}).get("id")
    logger.info("Created order id=%s", result.order_id)

    # Step 3: Add order lines
    lines = params.get("orderLines", params.get("lines", []))
    # For project invoices without explicit lines, create a default line
    if not lines and (project_ref or params.get("projectId")):
        proj_name = ""
        if isinstance(params.get("project"), str):
            proj_name = params["project"]
        elif isinstance(params.get("project"), dict):
            proj_name = params["project"].get("name", "Project")
        else:
            proj_name = "Project invoice"
        # Use budget or a descriptive line
        budget = params.get("budget") or params.get("fixedPrice") or 0
        lines = [
            {
                "description": proj_name,
                "unitPriceExcludingVatCurrency": budget if budget else 1,
                "count": 1,
            }
        ]
    if lines and result.order_id:
        build_and_post_order_lines(api_client, result.order_id, lines)

    # Step 4: Create invoice from order
    if result.order_id:
        try:
            invoice_params: dict[str, Any] = {
                "invoiceDate": params.get("invoiceDate") or today,
            }
            if params.get("send_invoice"):
                invoice_params["sendToCustomer"] = "true"
            inv_result = api_client.put(f"/order/{result.order_id}/:invoice", params=invoice_params)
            result.invoice_id = inv_result.get("value", {}).get("id")
            logger.info(
                "Created invoice id=%s from order id=%s",
                result.invoice_id,
                result.order_id,
            )
        except TripletexApiError as e:
            logger.warning("Invoice creation failed: %s", e)

    # Step 5: Register payment if requested
    payment = params.get("register_payment", params.get("payment"))
    if payment and result.invoice_id:
        pay_date = None
        pay_amount_override = None
        if isinstance(payment, dict):
            pay_date = payment.get("paymentDate")
            llm_amount = payment.get("amount")
            # Check if this is a partial/currency payment
            # (LLM amount differs from invoice amount → use LLM amount)
            if llm_amount and params.get("currency"):
                pay_amount_override = llm_amount
        result.payment_registered = _register_payment_on_invoice(
            api_client,
            result.invoice_id,
            payment_date=pay_date,
            amount_override=pay_amount_override,
        )

    return result
