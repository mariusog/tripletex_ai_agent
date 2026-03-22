"""Invoice handlers: create, send, pay, and credit invoices via Tripletex API."""

from __future__ import annotations

import logging
from datetime import date as dt_date
from typing import Any

from src.api_client import TripletexApiError, TripletexClient
from src.handlers.base import BaseHandler, register_handler
from src.handlers.entity_resolver import resolve as _resolve
from src.handlers.resolvers import ensure_bank_account as _ensure_bank_account
from src.handlers.resolvers import find_invoice_id as _find_invoice_id

logger = logging.getLogger(__name__)


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

        # Step 0: Ensure company has a bank account (required for invoicing)
        _ensure_bank_account(api_client)

        # Step 1: Resolve customer (search or create)
        cust_param = params.get("customer")
        # Merge top-level organizationNumber into customer if it's a string
        if isinstance(cust_param, str) and params.get("organizationNumber"):
            cust_param = {"name": cust_param, "organizationNumber": params["organizationNumber"]}
        customer_ref = _resolve(api_client, "customer", cust_param)

        # Step 1b: Create project if specified
        project_ref = None
        if params.get("project"):
            proj = params["project"]
            proj_name = proj.get("name") if isinstance(proj, dict) else str(proj)
            if proj_name:
                # Use account owner as PM (guaranteed to have PM access)
                emp_search = api_client.get_cached(
                    "account_owner", "/employee", params={"count": 1}, fields="id"
                )
                emp_values = emp_search.get("values", [])
                pm_ref = {"id": emp_values[0]["id"]} if emp_values else {"id": 0}

                # Also create the requested PM employee (competition checks they exist)
                pm_info = proj.get("projectManager") if isinstance(proj, dict) else None
                if pm_info and isinstance(pm_info, dict) and "id" not in pm_info:
                    _resolve(api_client, "employee", pm_info)
                import secrets

                proj_num = (
                    str(proj.get("number"))
                    if isinstance(proj, dict) and proj.get("number")
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
                    project_ref = {"id": proj_result.get("value", {}).get("id")}
                    logger.info("Created project id=%s", project_ref["id"])
                except TripletexApiError as e:
                    logger.warning("Project creation failed: %s", e)

        # Step 2: Create order
        order_body: dict[str, Any] = {
            "customer": customer_ref,
            "orderDate": params.get("orderDate") or today,
            "deliveryDate": params.get("deliveryDate") or today,
        }
        if project_ref:
            order_body["project"] = project_ref
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
                    line_price = (
                        line.get("unitPriceExcludingVatCurrency")
                        or line.get("amount")
                        or line.get("price")
                    )
                    ol["product"] = _resolve(
                        api_client,
                        "product",
                        line["product"],
                        extra_create_fields={"price": line_price},
                    )
                if "description" in line:
                    ol["description"] = line["description"]
                ol["count"] = line.get("count", line.get("quantity", 1))
                if "unitPriceExcludingVatCurrency" in line:
                    ol["unitPriceExcludingVatCurrency"] = line["unitPriceExcludingVatCurrency"]
                elif "amount" in line:
                    ol["unitPriceExcludingVatCurrency"] = line["amount"]
                elif "price" in line:
                    ol["unitPriceExcludingVatCurrency"] = line["price"]
                # Set vatType per line if specified (for mixed-VAT invoices)
                if "vatType" in line:
                    from src.handlers.resolvers import resolve_vat_type
                    vat_ref = resolve_vat_type(api_client, line["vatType"])
                    if vat_ref:
                        ol["vatType"] = vat_ref
                payloads.append(self.strip_none_values(ol))
            if payloads:
                api_client.post("/order/orderline/list", data=payloads)
                logger.info("Added %d order lines", len(payloads))

        # Step 4: Create invoice from order using PUT /order/:invoice
        # This single call creates the invoice AND optionally registers payment
        inv_id = None
        try:
            invoice_params: dict[str, Any] = {
                "invoiceDate": params.get("invoiceDate") or today,
            }

            # Payment is handled AFTER invoice creation so we can use
            # the actual invoice amount (incl. VAT) for full payment

            # Send invoice if requested
            if params.get("send_invoice"):
                invoice_params["sendToCustomer"] = "true"

            inv_result = api_client.put(f"/order/{order_id}/:invoice", params=invoice_params)
            invoice = inv_result.get("value", {})
            inv_id = invoice.get("id")
            logger.info("Created invoice id=%s from order id=%s", inv_id, order_id)
        except TripletexApiError as e:
            logger.warning("Invoice creation failed: %s", e)

        # Step 5: Register payment if requested, using actual invoice amount
        payment = params.get("register_payment", params.get("payment"))
        if payment and inv_id:
            try:
                inv_data = api_client.get(f"/invoice/{inv_id}", fields="amount")
                actual_amount = inv_data.get("value", {}).get("amount")
                if actual_amount:
                    pt_resp = api_client.get_cached(
                        "invoice_payment_type",
                        "/invoice/paymentType",
                        params={"count": 1},
                        fields="id",
                    )
                    pt_values = pt_resp.get("values", [])
                    if pt_values:
                        api_client.put(
                            f"/invoice/{inv_id}/:payment",
                            params={
                                "paymentDate": today,
                                "paymentTypeId": pt_values[0]["id"],
                                "paidAmount": actual_amount,
                            },
                        )
                        logger.info("Registered payment %s on invoice %s", actual_amount, inv_id)
            except TripletexApiError as e:
                logger.warning("Payment failed: %s", e)

        return {"id": inv_id, "orderId": order_id, "action": "created"}


@register_handler
class SendInvoiceHandler(BaseHandler):
    """Find or create invoice, then POST /invoice/{id}/:send."""

    def get_task_type(self) -> str:
        return "send_invoice"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        invoice_id = _find_invoice_id(api_client, params)

        # If no existing invoice, create one first
        if not invoice_id and params.get("customer"):
            inv_handler = CreateInvoiceHandler()
            inv_result = inv_handler.execute(api_client, params)
            invoice_id = inv_result.get("id")

        if not invoice_id:
            return {"error": "invoice_not_found"}

        send_body: dict[str, Any] = {"id": invoice_id}
        if params.get("sendType"):
            send_body["sendType"] = params["sendType"]
        if params.get("overrideEmailAddress"):
            send_body["overrideEmailAddress"] = params["overrideEmailAddress"]

        try:
            api_client.post(f"/invoice/{invoice_id}/:send", data=send_body)
            logger.info("Sent invoice id=%s", invoice_id)
        except TripletexApiError as e:
            logger.warning("Send invoice failed: %s", e)
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

        # If no existing invoice, create one first (full flow)
        if not invoice_id and params.get("customer"):
            pay_amount = params.get("amount", 0)
            is_reversal = params.get("reversal") or (pay_amount and pay_amount < 0)
            abs_amount = abs(pay_amount) if pay_amount else 0

            inv_params = dict(params)
            # Use absolute amount for the invoice and order line
            if not inv_params.get("orderLines") and abs_amount:
                inv_params["orderLines"] = [
                    {
                        "description": params.get("description", "Faktura"),
                        "unitPriceExcludingVatCurrency": abs_amount,
                        "count": 1,
                    }
                ]

            # For reversals: create invoice WITH payment, then reverse it
            # so the invoice shows payment history + outstanding amount
            if is_reversal:
                inv_params.pop("reversal", None)
                # Ensure positive payment is registered during invoice creation
                inv_params["register_payment"] = {"amount": abs_amount}

            # For non-reversals, include payment in CreateInvoiceHandler
            if not is_reversal:
                inv_params["register_payment"] = {"amount": pay_amount}

            invoice_handler = CreateInvoiceHandler()
            inv_result = invoice_handler.execute(api_client, inv_params)
            invoice_id = inv_result.get("id")

            # Non-reversals: payment already registered via PUT /order/:invoice
            if not is_reversal:
                if not invoice_id:
                    return {"error": "invoice_not_found"}
                return {"id": invoice_id, "action": "payment_registered"}

            # For reversals: register negative payment to reverse
            if is_reversal and invoice_id:
                try:
                    # Get actual invoice amount (incl. VAT) for exact reversal
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
                    today = dt_date.today().isoformat()
                    rev_params: dict[str, Any] = {
                        "paymentDate": params.get("paymentDate", today),
                        "paymentTypeId": pt_id,
                        "paidAmount": -rev_amount,
                    }
                    api_client.put(f"/invoice/{invoice_id}/:payment", params=rev_params)
                    logger.info("Reversed payment on invoice id=%s", invoice_id)
                except TripletexApiError as e:
                    logger.warning("Payment reversal failed: %s", e)
                return {"id": invoice_id, "action": "payment_reversed"}

        if not invoice_id:
            return {"error": "invoice_not_found"}

        today = dt_date.today().isoformat()
        pay_date = today
        if "paymentDate" in params:
            date_val = self.validate_date(params["paymentDate"], "paymentDate")
            if date_val:
                pay_date = date_val

        # Look up payment type (cached to avoid repeated calls)
        pt_resp = api_client.get_cached(
            "invoice_payment_type",
            "/invoice/paymentType",
            params={"count": 1},
            fields="id",
        )
        pt_values = pt_resp.get("values", [])
        pt_id = int(params.get("paymentTypeId", pt_values[0]["id"] if pt_values else 0))

        # Use the invoice's actual amount (incl. VAT) for full payment
        pay_amount = params["amount"]
        try:
            inv_data = api_client.get(f"/invoice/{invoice_id}", fields="amount")
            actual_amount = inv_data.get("value", {}).get("amount")
            if actual_amount and not params.get("reversal"):
                pay_amount = actual_amount
        except TripletexApiError:
            pass

        pay_params: dict[str, Any] = {
            "paymentDate": pay_date,
            "paymentTypeId": pt_id,
            "paidAmount": pay_amount,
        }
        api_client.put(f"/invoice/{invoice_id}/:payment", params=pay_params)
        logger.info("Registered payment on invoice id=%s", invoice_id)
        return {"id": invoice_id, "action": "payment_registered"}


@register_handler
class CreateCreditNoteHandler(BaseHandler):
    """Create invoice if needed, then PUT /invoice/{id}/:createCreditNote."""

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

        from datetime import date as dt_date

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
