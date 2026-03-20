"""Invoice handlers: create, send, pay, and credit invoices via Tripletex API."""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.handlers.order import CreateOrderHandler

logger = logging.getLogger(__name__)


@register_handler
class CreateInvoiceHandler(BaseHandler):
    """Full flow: create order -> add lines -> create invoice from order.

    Optimal: 2 calls (order + invoice, no lines) or 3 calls (with lines).
    """

    def get_task_type(self) -> str:
        return "create_invoice"

    @property
    def required_params(self) -> list[str]:
        return ["customer"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        # Step 1: Create order (reuse CreateOrderHandler)
        order_handler = CreateOrderHandler()
        order_result = order_handler.execute(api_client, params)
        order_id = order_result.get("id")
        if not order_id:
            return {"error": "order_creation_failed"}

        # Step 2: Create invoice from order
        inv_body: dict[str, Any] = {"orders": [{"id": order_id}]}

        for date_field in ("invoiceDate", "invoiceDueDate"):
            if date_field in params:
                date_val = self.validate_date(params[date_field], date_field)
                if date_val:
                    inv_body[date_field] = date_val

        if params.get("comment"):
            inv_body["comment"] = params["comment"]
        if "paymentTypeId" in params:
            inv_body["paymentTypeId"] = int(params["paymentTypeId"])

        inv_body = self.strip_none_values(inv_body)
        result = api_client.post("/invoice", data=inv_body)
        invoice = result.get("value", {})
        inv_id = invoice.get("id")
        logger.info("Created invoice id=%s from order id=%s", inv_id, order_id)
        return {"id": inv_id, "orderId": order_id, "action": "created"}


@register_handler
class SendInvoiceHandler(BaseHandler):
    """POST /invoice/{id}/:send. 1 API call."""

    def get_task_type(self) -> str:
        return "send_invoice"

    @property
    def required_params(self) -> list[str]:
        return ["invoiceId"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        invoice_id = int(params["invoiceId"])
        send_body: dict[str, Any] = {"id": invoice_id}
        if params.get("sendType"):
            send_body["sendType"] = params["sendType"]
        if params.get("overrideEmailAddress"):
            send_body["overrideEmailAddress"] = params["overrideEmailAddress"]

        api_client.post(f"/invoice/{invoice_id}/:send", data=send_body)
        logger.info("Sent invoice id=%s", invoice_id)
        return {"id": invoice_id, "action": "sent"}


@register_handler
class RegisterPaymentHandler(BaseHandler):
    """Find invoice then POST /invoice/{id}/:payment.

    Optimal: 1 call (direct ID) or 2 calls (search + payment).
    """

    def get_task_type(self) -> str:
        return "register_payment"

    @property
    def required_params(self) -> list[str]:
        return ["amount"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        invoice_id = _find_invoice_id(api_client, params)
        if not invoice_id:
            return {"error": "invoice_not_found"}

        pay_body: dict[str, Any] = {"amount": params["amount"]}
        if "paymentDate" in params:
            date_val = self.validate_date(params["paymentDate"], "paymentDate")
            if date_val:
                pay_body["paymentDate"] = date_val
        if "paymentTypeId" in params:
            pay_body["paymentTypeId"] = int(params["paymentTypeId"])

        api_client.post(f"/invoice/{invoice_id}/:payment", data=pay_body)
        logger.info("Registered payment on invoice id=%s", invoice_id)
        return {"id": invoice_id, "action": "payment_registered"}


@register_handler
class CreateCreditNoteHandler(BaseHandler):
    """Find invoice then POST /invoice/{id}/:createCreditNote.

    Optimal: 1 call (direct ID) or 2 calls (search + credit note).
    """

    def get_task_type(self) -> str:
        return "create_credit_note"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        invoice_id = _find_invoice_id(api_client, params)
        if not invoice_id:
            return {"error": "invoice_not_found"}

        cn_body: dict[str, Any] = {}
        if params.get("comment"):
            cn_body["comment"] = params["comment"]
        if "creditNoteDate" in params:
            date_val = self.validate_date(params["creditNoteDate"], "creditNoteDate")
            if date_val:
                cn_body["date"] = date_val

        result = api_client.post(f"/invoice/{invoice_id}/:createCreditNote", data=cn_body)
        credit_note = result.get("value", {}) if result else {}
        cn_id = credit_note.get("id")
        logger.info("Created credit note id=%s for invoice id=%s", cn_id, invoice_id)
        return {"id": cn_id, "invoiceId": invoice_id, "action": "credit_note_created"}


def _find_invoice_id(api_client: TripletexClient, params: dict[str, Any]) -> int | None:
    """Resolve invoice ID: direct ID avoids a GET call, otherwise search."""
    if "invoiceId" in params:
        return int(params["invoiceId"])
    search_params: dict[str, Any] = {"count": 1}
    if "invoiceNumber" in params:
        search_params["invoiceNumber"] = params["invoiceNumber"]
    elif "customer" in params:
        cust = params["customer"]
        search_params["customerId"] = int(cust) if not isinstance(cust, dict) else cust["id"]
    else:
        return None
    resp = api_client.get("/invoice", params=search_params)
    values = resp.get("values", [])
    if not values:
        return None
    inv_id: int | None = values[0].get("id")
    return inv_id
