"""Invoice handlers: create, send, pay, and credit invoices via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexClient, TripletexApiError
from src.handlers.base import BaseHandler, register_handler

logger = logging.getLogger(__name__)


def _resolve_customer(api_client: TripletexClient, customer: Any) -> dict[str, int]:
    """Resolve customer to {"id": N}. Creates if not found by name."""
    if customer is None:
        return {"id": 0}
    if isinstance(customer, dict) and "id" in customer:
        return {"id": int(customer["id"])}
    if isinstance(customer, (int, float)):
        return {"id": int(customer)}
    try:
        return {"id": int(customer)}
    except (TypeError, ValueError):
        pass
    name = str(customer) if not isinstance(customer, dict) else customer.get("name", "")
    if not name:
        return {"id": 0}
    resp = api_client.get("/customer", params={"name": name, "count": 1}, fields="id,name")
    values = resp.get("values", [])
    if values:
        return {"id": values[0]["id"]}
    # Create the customer
    org_nr = customer.get("organizationNumber") if isinstance(customer, dict) else None
    cust_body: dict[str, Any] = {"name": name}
    if org_nr:
        cust_body["organizationNumber"] = str(org_nr)
    result = api_client.post("/customer", data=cust_body)
    cust_id = result.get("value", {}).get("id")
    logger.info("Auto-created customer '%s' id=%s", name, cust_id)
    return {"id": cust_id}


def _resolve_product(api_client: TripletexClient, product: Any) -> dict[str, int]:
    """Resolve product to {"id": N}. Creates if not found."""
    if isinstance(product, dict) and "id" in product:
        return {"id": int(product["id"])}
    if isinstance(product, (int, float)):
        return {"id": int(product)}
    try:
        return {"id": int(product)}
    except (TypeError, ValueError):
        pass
    name = str(product) if not isinstance(product, dict) else product.get("name", "")
    number = product.get("number") if isinstance(product, dict) else None
    # Search by number first (more precise), then by name
    if number:
        resp = api_client.get("/product", params={"number": str(number), "count": 1}, fields="id")
        values = resp.get("values", [])
        if values:
            return {"id": values[0]["id"]}
    if name:
        resp = api_client.get("/product", params={"name": name, "count": 1}, fields="id")
        values = resp.get("values", [])
        if values:
            return {"id": values[0]["id"]}
    # Create the product
    prod_body: dict[str, Any] = {"name": name or f"Product {number}"}
    if number:
        prod_body["number"] = int(number)
    result = api_client.post("/product", data=prod_body)
    prod_id = result.get("value", {}).get("id")
    logger.info("Auto-created product '%s' id=%s", name, prod_id)
    return {"id": prod_id}


@register_handler
class CreateInvoiceHandler(BaseHandler):
    """Full flow: resolve entities -> create order -> add lines -> invoice -> payment.

    Handles the common competition pattern of multi-step invoice tasks.
    """

    def get_task_type(self) -> str:
        return "create_invoice"

    @property
    def required_params(self) -> list[str]:
        return ["customer"]

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        today = dt_date.today().isoformat()

        # Step 1: Resolve customer (search or create)
        customer_ref = _resolve_customer(api_client, params.get("customer"))

        # Step 2: Create order
        order_body: dict[str, Any] = {
            "customer": customer_ref,
            "orderDate": params.get("orderDate") or today,
            "deliveryDate": params.get("deliveryDate") or today,
        }
        order_body = self.strip_none_values(order_body)
        order_result = api_client.post("/order", data=order_body)
        order_id = order_result.get("value", {}).get("id")
        logger.info("Created order id=%s", order_id)

        # Step 3: Add order lines
        lines = params.get("orderLines", params.get("lines", []))
        if lines:
            payloads = []
            for line in lines:
                ol: dict[str, Any] = {"order": {"id": order_id}}
                if "product" in line:
                    ol["product"] = _resolve_product(api_client, line["product"])
                if "description" in line:
                    ol["description"] = line["description"]
                ol["count"] = line.get("count", line.get("quantity", 1))
                if "unitPriceExcludingVatCurrency" in line:
                    ol["unitPriceExcludingVatCurrency"] = line["unitPriceExcludingVatCurrency"]
                elif "amount" in line:
                    ol["unitPriceExcludingVatCurrency"] = line["amount"]
                elif "price" in line:
                    ol["unitPriceExcludingVatCurrency"] = line["price"]
                payloads.append(self.strip_none_values(ol))
            if payloads:
                api_client.post("/order/orderline/list", data=payloads)
                logger.info("Added %d order lines", len(payloads))

        # Step 4: Create invoice from order
        inv_id = None
        try:
            inv_body: dict[str, Any] = {
                "invoiceDate": params.get("invoiceDate") or today,
                "invoiceDueDate": params.get("invoiceDueDate") or today,
                "orders": [{"id": order_id}],
            }
            inv_body = self.strip_none_values(inv_body)
            inv_result = api_client.post("/invoice", data=inv_body)
            invoice = inv_result.get("value", {})
            inv_id = invoice.get("id")
            logger.info("Created invoice id=%s from order id=%s", inv_id, order_id)
        except TripletexApiError as e:
            logger.warning("Invoice creation failed: %s", e)

        # Step 5: Register payment if requested (PUT with query params)
        payment = params.get("register_payment", params.get("payment"))
        if payment and inv_id:
            if isinstance(payment, dict):
                pay_amount = payment.get("amount")
                pay_date = payment.get("paymentDate")
            else:
                pay_amount = payment
                pay_date = None
            if not pay_amount and "totalAmount" in params:
                pay_amount = params["totalAmount"]

            if pay_amount:
                try:
                    # Look up a payment type
                    pt_resp = api_client.get(
                        "/invoice/paymentType", params={"count": 1}, fields="id"
                    )
                    pt_values = pt_resp.get("values", [])
                    pt_id = pt_values[0]["id"] if pt_values else 0

                    pay_params: dict[str, Any] = {
                        "paymentDate": pay_date or today,
                        "paymentTypeId": pt_id,
                        "paidAmount": pay_amount,
                    }
                    api_client.put(
                        f"/invoice/{inv_id}/:payment", params=pay_params
                    )
                    logger.info(
                        "Registered payment of %s on invoice %s", pay_amount, inv_id
                    )
                except TripletexApiError as e:
                    logger.warning("Payment failed: %s", e)

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
        from datetime import date as dt_date

        invoice_id = _find_invoice_id(api_client, params)
        if not invoice_id:
            return {"error": "invoice_not_found"}

        today = dt_date.today().isoformat()
        pay_date = today
        if "paymentDate" in params:
            date_val = self.validate_date(params["paymentDate"], "paymentDate")
            if date_val:
                pay_date = date_val

        # Look up payment type
        pt_resp = api_client.get(
            "/invoice/paymentType", params={"count": 1}, fields="id"
        )
        pt_values = pt_resp.get("values", [])
        pt_id = int(params.get("paymentTypeId", pt_values[0]["id"] if pt_values else 0))

        pay_params: dict[str, Any] = {
            "paymentDate": pay_date,
            "paymentTypeId": pt_id,
            "paidAmount": params["amount"],
        }
        api_client.put(f"/invoice/{invoice_id}/:payment", params=pay_params)
        logger.info("Registered payment on invoice id=%s", invoice_id)
        return {"id": invoice_id, "action": "payment_registered"}


@register_handler
class CreateCreditNoteHandler(BaseHandler):
    """Create invoice if needed, then POST /invoice/{id}/:createCreditNote."""

    def get_task_type(self) -> str:
        return "create_credit_note"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        invoice_id = _find_invoice_id(api_client, params)

        # If no existing invoice, create one first (full flow)
        if not invoice_id and params.get("customer"):
            invoice_handler = CreateInvoiceHandler()
            inv_result = invoice_handler.execute(api_client, params)
            invoice_id = inv_result.get("id")

        if not invoice_id:
            return {"error": "invoice_not_found"}

        cn_body: dict[str, Any] = {}
        if params.get("comment"):
            cn_body["comment"] = params["comment"]
        if "creditNoteDate" in params:
            date_val = self.validate_date(params["creditNoteDate"], "creditNoteDate")
            if date_val:
                cn_body["date"] = date_val

        try:
            result = api_client.post(f"/invoice/{invoice_id}/:createCreditNote", data=cn_body)
            credit_note = result.get("value", {}) if result else {}
            cn_id = credit_note.get("id")
            logger.info("Created credit note id=%s for invoice id=%s", cn_id, invoice_id)
            return {"id": cn_id, "invoiceId": invoice_id, "action": "credit_note_created"}
        except TripletexApiError as e:
            logger.warning("Credit note creation failed: %s", e)
            return {"invoiceId": invoice_id, "action": "invoice_created_credit_note_failed"}


def _find_invoice_id(api_client: TripletexClient, params: dict[str, Any]) -> int | None:
    """Resolve invoice ID: direct ID avoids a GET call, otherwise search."""
    if "invoiceId" in params:
        return int(params["invoiceId"])
    search_params: dict[str, Any] = {"count": 1}
    if "invoiceNumber" in params:
        search_params["invoiceNumber"] = params["invoiceNumber"]
    elif "customer" in params:
        cust = params["customer"]
        if isinstance(cust, dict):
            if "id" in cust:
                search_params["customerId"] = int(cust["id"])
            elif "name" in cust:
                # Can't search invoice by customer name directly
                return None
            else:
                return None
        else:
            try:
                search_params["customerId"] = int(cust)
            except (TypeError, ValueError):
                return None
    else:
        return None
    try:
        resp = api_client.get("/invoice", params=search_params)
        values = resp.get("values", [])
        if not values:
            return None
        return values[0].get("id")
    except TripletexApiError:
        return None
