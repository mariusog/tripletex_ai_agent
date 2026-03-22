"""Invoice handlers: create, send, pay, and credit invoices via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.api_helpers import find_invoice_id as _find_invoice_id
from src.handlers.base import BaseHandler, ParamSpec, register_handler
from src.services.invoice_service import create_full_invoice

logger = logging.getLogger(__name__)


@register_handler
class CreateInvoiceHandler(BaseHandler):
    """Full flow: resolve entities -> create order -> add lines -> invoice -> payment."""

    tier = 2
    description = "Create invoice with order lines and optional payment"
    param_schema = {
        "customer": ParamSpec(description="Customer name or {name, organizationNumber}"),
        "invoiceDate": ParamSpec(required=False, type="date"),
        "invoiceDueDate": ParamSpec(required=False, type="date"),
        "orderLines": ParamSpec(
            required=False, type="list", description="Line items with product, count, price"
        ),
        "register_payment": ParamSpec(
            required=False, type="object", description="{amount, paymentDate}"
        ),
    }

    def get_task_type(self) -> str:
        return "create_invoice"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        result = create_full_invoice(api_client, params)
        return {"id": result.invoice_id, "orderId": result.order_id, "action": "created"}


@register_handler
class SendInvoiceHandler(BaseHandler):
    """Find or create invoice, then POST /invoice/{id}/:send."""

    tier = 2
    description = "Send an invoice to customer"

    def get_task_type(self) -> str:
        return "send_invoice"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        invoice_id = _find_invoice_id(api_client, params)

        if not invoice_id and params.get("customer"):
            result = create_full_invoice(api_client, params)
            invoice_id = result.invoice_id

        if not invoice_id:
            return {"error": "invoice_not_found"}

        send_type = params.get("sendType", "EMAIL")
        send_params: dict[str, Any] = {"sendType": send_type}
        if params.get("overrideEmailAddress"):
            send_params["overrideEmailAddress"] = params["overrideEmailAddress"]

        try:
            api_client.put(
                f"/invoice/{invoice_id}/:send",
                params=send_params,
                data={"id": invoice_id},
            )
            logger.info("Sent invoice id=%s", invoice_id)
        except TripletexApiError as e:
            logger.warning("Send invoice failed: %s", e)
        return {"id": invoice_id, "action": "sent"}


@register_handler
class RegisterPaymentHandler(BaseHandler):
    """Find invoice then register payment. Creates invoice first if needed."""

    tier = 2
    description = "Register payment on an invoice"
    disambiguation = (
        "For currency payments: amount should be in NOK at the PAYMENT exchange rate, "
        "not the invoice rate. E.g. 13986 EUR at payment rate 11.31 = 158201.66 NOK."
    )
    param_schema = {
        "customer": ParamSpec(required=False),
        "amount": ParamSpec(type="number", description="Payment amount in NOK"),
        "paymentDate": ParamSpec(required=False, type="date"),
        "reversal": ParamSpec(required=False, type="boolean"),
        "orderLines": ParamSpec(required=False, type="list"),
        "exchangeRate": ParamSpec(
            required=False, type="number", description="Payment exchange rate"
        ),
        "currencyAmount": ParamSpec(
            required=False, type="number", description="Amount in foreign currency"
        ),
    }

    def get_task_type(self) -> str:
        return "register_payment"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today().isoformat()

        # Use overdue invoice for partial payment (late fee flow)
        overdue_id = params.get("_overdue_invoice_id")
        if overdue_id:
            # Always use overdue invoice for payment — the invoiceId from
            # context might be the reminder fee invoice, not the overdue one
            params["invoiceId"] = overdue_id

        invoice_id = _find_invoice_id(api_client, params)

        # If no existing invoice, create one first (full flow)
        if not invoice_id and params.get("customer"):
            pay_amount = params.get("amount", 0)
            is_reversal = params.get("reversal") or (pay_amount and pay_amount < 0)
            abs_amount = abs(pay_amount) if pay_amount else 0

            inv_params = dict(params)

            # Fix order line amounts for currency payments
            # If orderLines amount == currencyAmount, it's in foreign currency
            # Use the NOK payment amount instead
            currency_amt = params.get("currencyAmount")
            existing_lines = inv_params.get("orderLines", [])
            if currency_amt and existing_lines:
                for line in existing_lines:
                    line_amt = line.get("amount") or line.get("unitPriceExcludingVatCurrency") or 0
                    if abs(line_amt - currency_amt) < 1:
                        line["unitPriceExcludingVatCurrency"] = abs_amount
                        line.pop("amount", None)

            if not inv_params.get("orderLines") and abs_amount:
                inv_params["orderLines"] = [
                    {
                        "description": params.get("description", "Faktura"),
                        "unitPriceExcludingVatCurrency": abs_amount,
                        "count": 1,
                    }
                ]

            if is_reversal:
                inv_params.pop("reversal", None)
                inv_params["register_payment"] = {"amount": abs_amount}
            else:
                inv_params["register_payment"] = {"amount": pay_amount}

            result = create_full_invoice(api_client, inv_params)
            invoice_id = result.invoice_id

            if not is_reversal:
                if not invoice_id:
                    return {"error": "invoice_not_found"}
                return {"id": invoice_id, "action": "payment_registered"}

            # For reversals: register negative payment
            if is_reversal and invoice_id:
                try:
                    inv_data = api_client.get(f"/invoice/{invoice_id}", fields="amount")
                    rev_amount = inv_data.get("value", {}).get("amount", abs_amount)
                    pt_resp = api_client.get_cached(
                        "invoice_payment_type",
                        "/invoice/paymentType",
                        params={"count": 1},
                        fields="id",
                    )
                    pt_values = pt_resp.get("values", [])
                    pt_id = pt_values[0]["id"] if pt_values else 0
                    api_client.put(
                        f"/invoice/{invoice_id}/:payment",
                        params={
                            "paymentDate": params.get("paymentDate", today),
                            "paymentTypeId": pt_id,
                            "paidAmount": -rev_amount,
                        },
                    )
                    logger.info("Reversed payment on invoice id=%s", invoice_id)
                except TripletexApiError as e:
                    logger.warning("Payment reversal failed: %s", e)
                return {"id": invoice_id, "action": "payment_reversed"}

        if not invoice_id:
            return {"error": "invoice_not_found"}

        pay_date = today
        if "paymentDate" in params:
            date_val = self.validate_date(params["paymentDate"], "paymentDate")
            if date_val:
                pay_date = date_val

        pt_resp = api_client.get_cached(
            "invoice_payment_type",
            "/invoice/paymentType",
            params={"count": 1},
            fields="id",
        )
        pt_values = pt_resp.get("values", [])
        pt_id = int(params.get("paymentTypeId", pt_values[0]["id"] if pt_values else 0))

        pay_amount = params.get("amount", 0)
        # For non-partial payments, use the actual invoice amount
        try:
            inv_data = api_client.get(f"/invoice/{invoice_id}", fields="amount")
            actual_amount = inv_data.get("value", {}).get("amount")
            if actual_amount:
                if params.get("reversal"):
                    pay_amount = -abs(actual_amount)  # Reverse full amount
                elif not pay_amount or abs(pay_amount) >= abs(actual_amount) * 0.8:
                    pay_amount = actual_amount  # Full payment — use exact amount
        except TripletexApiError:
            pass

        api_client.put(
            f"/invoice/{invoice_id}/:payment",
            params={
                "paymentDate": pay_date,
                "paymentTypeId": pt_id,
                "paidAmount": pay_amount,
            },
        )
        logger.info("Registered payment on invoice id=%s", invoice_id)
        return {"id": invoice_id, "action": "payment_registered"}


@register_handler
class CreateCreditNoteHandler(BaseHandler):
    """Create invoice if needed, then PUT /invoice/{id}/:createCreditNote."""

    tier = 2
    description = "Create a credit note for an invoice"
    param_schema = {
        "customer": ParamSpec(description="Customer name or ref"),
        "orderLines": ParamSpec(required=False, type="list"),
        "comment": ParamSpec(required=False, description="Reason for credit note"),
        "creditNoteDate": ParamSpec(required=False, type="date"),
    }

    def get_task_type(self) -> str:
        return "create_credit_note"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        invoice_id = _find_invoice_id(api_client, params)

        if not invoice_id and params.get("customer"):
            result = create_full_invoice(api_client, params)
            invoice_id = result.invoice_id

        if not invoice_id:
            return {"error": "invoice_not_found"}

        cn_params: dict[str, Any] = {
            "date": dt_date.today().isoformat(),
        }
        if "creditNoteDate" in params:
            date_val = self.validate_date(params["creditNoteDate"], "creditNoteDate")
            if date_val:
                cn_params["date"] = date_val
        if params.get("comment"):
            cn_params["comment"] = params["comment"]

        try:
            result = api_client.put(f"/invoice/{invoice_id}/:createCreditNote", params=cn_params)
            credit_note = result.get("value", {}) if result else {}
            cn_id = credit_note.get("id")
            logger.info("Created credit note id=%s for invoice id=%s", cn_id, invoice_id)
            return {"id": cn_id, "invoiceId": invoice_id, "action": "credit_note_created"}
        except TripletexApiError as e:
            logger.warning("Credit note creation failed: %s", e)
            return {"invoiceId": invoice_id, "action": "invoice_created_credit_note_failed"}
