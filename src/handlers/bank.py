"""Bank reconciliation handler via Tripletex API.

Handles the full bank reconciliation flow:
1. Process customer payments (create customer, invoice, register payment)
2. Process supplier payments (create supplier, voucher)
3. Process bank fees (voucher postings)
"""

from __future__ import annotations

import logging
from typing import Any

from src.api_client import TripletexClient
from src.handlers.api_helpers import ensure_bank_account
from src.handlers.base import BaseHandler, register_handler
from src.handlers.entity_resolver import resolve as _resolve
from src.services.invoice_service import create_full_invoice

logger = logging.getLogger(__name__)


@register_handler
class BankReconciliationHandler(BaseHandler):
    """Process bank statement: match payments to invoices and suppliers."""

    tier = 3
    description = "Perform bank reconciliation from bank statement"

    def get_task_type(self) -> str:
        return "bank_reconciliation"

    def execute(self, api_client: TripletexClient, params: dict[str, Any]) -> dict[str, Any]:
        ensure_bank_account(api_client)
        results: dict[str, Any] = {"action": "reconciled", "payments": []}

        # Convert flat "transactions" into customerPayments/supplierPayments
        if "transactions" in params and not params.get("customerPayments"):
            cust_payments = []
            sup_payments = []
            fees = []
            for tx in params["transactions"]:
                if tx.get("customer") and tx.get("amountIn"):
                    cust_payments.append(
                        {
                            "customer": tx["customer"],
                            "amount": tx["amountIn"],
                            "date": tx.get("date", ""),
                            "invoiceNumber": tx.get("invoiceNumber"),
                        }
                    )
                elif tx.get("supplier") and tx.get("amountOut"):
                    sup_payments.append(
                        {
                            "supplier": tx["supplier"],
                            "amount": tx["amountOut"],
                            "date": tx.get("date", ""),
                        }
                    )
                elif tx.get("amountIn") or tx.get("amountOut"):
                    fees.append(
                        {
                            "amount": tx.get("amountOut") or tx.get("amountIn", 0),
                            "date": tx.get("date", ""),
                            "description": tx.get("description", "Bankgebyr"),
                        }
                    )
            if cust_payments:
                params["customerPayments"] = cust_payments
            if sup_payments:
                params["supplierPayments"] = sup_payments
            if fees:
                params["bankFees"] = fees

        # Process customer payments (incoming)
        for cp in params.get("customerPayments", []):
            self._process_customer_payment(api_client, cp, results)

        # Process supplier payments (outgoing)
        for sp in params.get("supplierPayments", []):
            self._process_supplier_payment(api_client, sp, results)

        # Process bank fees
        for fee in params.get("bankFees", []):
            self._process_bank_fee(api_client, fee, results)

        # If no structured data, fall back to basic reconciliation
        if not any(params.get(k) for k in ("customerPayments", "supplierPayments", "bankFees")):
            return self._basic_reconciliation(api_client, params)

        return results

    def _process_customer_payment(
        self, api_client: TripletexClient, cp: dict[str, Any], results: dict
    ) -> None:
        """Find existing invoice and register payment. Create only if not found."""
        try:
            from src.api_client import TripletexApiError

            customer_name = cp.get("customer", "")
            amount = cp.get("amount", 0)
            date = cp.get("date", "")
            inv_num = cp.get("invoiceNumber", "")

            # Try to find existing invoice first
            invoice_id = None
            search: dict[str, Any] = {"count": 10}
            if inv_num:
                search["invoiceNumber"] = inv_num
            # Search by customer name
            if customer_name:
                try:
                    cust_resp = api_client.get(
                        "/customer",
                        params={"name": customer_name, "count": 5},
                        fields="id,name",
                    )
                    for cv in cust_resp.get("values", []):
                        if cv.get("name", "").strip().lower() == customer_name.strip().lower():
                            search["customerId"] = cv["id"]
                            break
                except TripletexApiError:
                    pass

            if "customerId" in search or "invoiceNumber" in search:
                try:
                    inv_resp = api_client.get(
                        "/invoice", params=search, fields="id,amount,amountOutstanding"
                    )
                    for inv in inv_resp.get("values", []):
                        outstanding = inv.get("amountOutstanding") or inv.get("amount", 0)
                        if outstanding > 0:
                            invoice_id = inv["id"]
                            break
                except TripletexApiError:
                    pass

            if invoice_id:
                # Register payment on existing invoice
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
                        "paymentDate": date,
                        "paymentTypeId": pt_id,
                        "paidAmount": amount,
                    },
                )
                results["payments"].append(
                    {
                        "customer": customer_name,
                        "invoice_id": invoice_id,
                        "amount": amount,
                        "status": "paid",
                    }
                )
            else:
                # No existing invoice — create new one with payment
                inv_result = create_full_invoice(
                    api_client,
                    {
                        "customer": {"name": customer_name},
                        "orderLines": [
                            {
                                "description": f"Faktura {inv_num}" if inv_num else "Faktura",
                                "unitPriceExcludingVatCurrency": amount,
                                "count": 1,
                            }
                        ],
                        "register_payment": {"amount": amount, "paymentDate": date},
                    },
                )
                results["payments"].append(
                    {
                        "customer": customer_name,
                        "invoice_id": inv_result.invoice_id,
                        "amount": amount,
                        "status": "paid",
                    }
                )
        except Exception as e:
            logger.warning("Customer payment failed for %s: %s", cp.get("customer"), e)

    def _process_supplier_payment(
        self, api_client: TripletexClient, sp: dict[str, Any], results: dict
    ) -> None:
        """Create supplier and voucher for supplier payment."""
        try:
            supplier_name = sp.get("supplier", "")
            amount = abs(sp.get("amount", 0))
            date = sp.get("date", "")

            # Resolve supplier
            supplier_ref = _resolve(api_client, "supplier", {"name": supplier_name})

            # Create voucher: debit AP (2400), credit bank (1920)
            from src.services.posting_builder import resolve_account as _resolve_account

            bank_acct, _ = _resolve_account(api_client, 1920)
            ap_acct, _ = _resolve_account(api_client, 2400)

            body: dict[str, Any] = {
                "date": date,
                "description": f"Betaling {supplier_name}",
                "postings": [
                    {
                        "row": 1,
                        "account": ap_acct,
                        "amountGross": amount,
                        "amountGrossCurrency": amount,
                        "supplier": supplier_ref,
                    },
                    {
                        "row": 2,
                        "account": bank_acct,
                        "amountGross": -amount,
                        "amountGrossCurrency": -amount,
                    },
                ],
            }
            result = api_client.post("/ledger/voucher", data=body, params={"sendToLedger": "true"})
            results["payments"].append(
                {
                    "supplier": supplier_name,
                    "voucher_id": result.get("value", {}).get("id"),
                    "amount": amount,
                    "status": "paid",
                }
            )
        except Exception as e:
            logger.warning("Supplier payment failed for %s: %s", sp.get("supplier"), e)

    def _process_bank_fee(
        self, api_client: TripletexClient, fee: dict[str, Any], results: dict
    ) -> None:
        """Create voucher for bank fee."""
        try:
            amount = fee.get("amount", 0)
            date = fee.get("date", "")
            desc = fee.get("description", "Bankgebyr")

            from src.services.posting_builder import resolve_account

            bank_acct, _ = resolve_account(api_client, 1920)
            fee_acct, _ = resolve_account(api_client, 7770)

            # Bank fee = expense: debit fee account, credit bank
            fee_abs = abs(amount)
            body: dict[str, Any] = {
                "date": date,
                "description": desc,
                "postings": [
                    {
                        "row": 1,
                        "account": fee_acct,
                        "amountGross": fee_abs,
                        "amountGrossCurrency": fee_abs,
                    },
                    {
                        "row": 2,
                        "account": bank_acct,
                        "amountGross": -fee_abs,
                        "amountGrossCurrency": -fee_abs,
                    },
                ],
            }
            api_client.post("/ledger/voucher", data=body, params={"sendToLedger": "true"})
        except Exception as e:
            logger.warning("Bank fee voucher failed: %s", e)

    def _basic_reconciliation(
        self, api_client: TripletexClient, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Fallback: create basic bank reconciliation record."""
        from datetime import date as dt_date

        resp = api_client.get(
            "/ledger/account",
            params={"number": str(params.get("accountNumber", "1920")), "count": 1},
            fields="id",
        )
        values = resp.get("values", [])
        account_id = values[0]["id"] if values else 0

        body: dict[str, Any] = {
            "account": {"id": int(account_id)},
            "type": params.get("type", "MANUAL"),
        }

        try:
            today = dt_date.today().isoformat()
            period_resp = api_client.get(
                "/ledger/accountingPeriod",
                params={"dateFrom": today, "dateTo": today, "count": 1},
                fields="id",
            )
            period_vals = period_resp.get("values", [])
            if period_vals:
                body["accountingPeriod"] = {"id": period_vals[0]["id"]}
        except Exception:
            logger.warning("Could not find accounting period")

        result = api_client.post("/bank/reconciliation", data=body)
        value = result.get("value", {})
        return {"id": value.get("id"), "action": "created"}
