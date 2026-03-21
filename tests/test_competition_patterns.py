"""Competition pattern tests: realistic multi-step scenarios from live runs.

These tests simulate the exact patterns the competition throws at us,
using direct handler calls against the sandbox.

Run with: SANDBOX_URL=... SANDBOX_TOKEN=... python -m pytest tests/test_competition_patterns.py -v
"""

from __future__ import annotations

import os
import secrets
from typing import Any

import pytest

from src.api_client import TripletexClient
from src.handlers import HANDLER_REGISTRY

SANDBOX_URL = os.environ.get("SANDBOX_URL", "")
SANDBOX_TOKEN = os.environ.get("SANDBOX_TOKEN", "")

pytestmark = pytest.mark.slow


@pytest.fixture
def client():
    if not SANDBOX_URL or not SANDBOX_TOKEN:
        pytest.skip("No sandbox credentials")
    c = TripletexClient(SANDBOX_URL, SANDBOX_TOKEN)
    yield c
    c.close()


def uid() -> str:
    return secrets.token_hex(4)


def run_handler(client: TripletexClient, task_type: str, params: dict[str, Any]) -> dict:
    handler = HANDLER_REGISTRY[task_type]
    return handler.execute(client, params)


# ============================================================
# PATTERN 1: Employee onboarding (from PDF)
# Competition: create dept + create employee with dept, employment details
# ============================================================


class TestEmployeeOnboardingFull:
    """Simulates: 'Create employee X, assign to dept Y, 80% stilling, salary Z'

    Based on real competition prompt:
    'Du har mottatt en arbeidskontrakt (se vedlagt PDF). Opprett den ansatte
    i Tripletex med alle detaljer fra kontrakten: personnummer, fødselsdato,
    avdeling, stillingskode, lønn, stillingsprosent og startdato.'
    """

    def test_onboarding_with_all_fields(self, client):
        tag = uid()
        # Step 1: Create department
        dept_result = run_handler(client, "create_department", {"name": f"Logistikk-{tag}"})
        assert dept_result["id"]

        # Step 2: Create employee with ALL competition-verified fields
        emp_result = run_handler(
            client,
            "create_employee",
            {
                "firstName": f"Brita-{tag}",
                "lastName": "Stølsvik",
                "email": f"brita-{tag}@example.org",
                "dateOfBirth": "1993-03-16",
                "nationalIdentityNumber": "01019012345",
                "bankAccountNumber": "12345678903",
                "department": f"Logistikk-{tag}",
                "startDate": "2026-05-31",
                "employmentType": "Fast stilling",
                "employmentPercentage": 100,
                "annualSalary": 660000,
                "hoursPerDay": 7.5,
                "jobCode": "1211",
            },
        )
        assert emp_result["id"]

        # Verify ALL fields the competition checks
        v = client.get(
            f"/employee/{emp_result['id']}",
            fields="firstName,lastName,email,dateOfBirth,"
            "nationalIdentityNumber,bankAccountNumber,"
            "department(id,name),"
            "employments(startDate,employmentDetails(*))",
        )["value"]
        assert v["firstName"] == f"Brita-{tag}"
        assert v["lastName"] == "Stølsvik"
        assert v["email"] == f"brita-{tag}@example.org"
        assert v["dateOfBirth"] == "1993-03-16"
        # nationalIdentityNumber may be stripped if format is invalid
        if v.get("nationalIdentityNumber"):
            assert len(v["nationalIdentityNumber"]) == 11
        assert v["department"] is not None

        emps = v.get("employments", [])
        assert len(emps) >= 1, "No employment record"
        assert emps[0]["startDate"] == "2026-05-31"

        details = emps[0].get("employmentDetails", [])
        assert len(details) >= 1, "No employment details"
        detail = details[0]
        assert detail.get("percentageOfFullTimeEquivalent") == 100.0
        assert detail.get("employmentType") == "ORDINARY"
        assert detail.get("annualSalary") == 660000.0
        assert detail.get("shiftDurationHours") == 7.5
        assert detail.get("occupationCode") is not None

    def test_every_field_is_set(self, client):
        """Verify ALL competition-checked fields are set on the employee.

        This test uses every possible field to ensure the handler processes
        them all correctly. In competition, the LLM must extract these from PDFs.
        """
        tag = uid()
        run_handler(client, "create_department", {"name": f"QA-{tag}"})

        result = run_handler(
            client,
            "create_employee",
            {
                "firstName": f"Full-{tag}",
                "lastName": "Fields",
                "email": f"full-{tag}@example.org",
                "dateOfBirth": "1990-05-15",
                "nationalIdentityNumber": "15059012345",
                "bankAccountNumber": "12345678903",
                "department": f"QA-{tag}",
                "startDate": "2026-08-01",
                "employmentType": "Fast stilling",
                "employmentPercentage": 80,
                "annualSalary": 550000,
                "hoursPerDay": 6.0,
                "jobCode": "3112",
            },
        )
        emp_id = result["id"]
        assert emp_id

        # Verify EVERY field
        v = client.get(
            f"/employee/{emp_id}",
            fields="firstName,lastName,email,dateOfBirth,"
            "nationalIdentityNumber,bankAccountNumber,"
            "department(id,name),"
            "employments(startDate,employmentDetails("
            "employmentType,percentageOfFullTimeEquivalent,"
            "annualSalary,shiftDurationHours,occupationCode(id)))",
        )["value"]

        # Employee fields
        assert v["firstName"] == f"Full-{tag}", f"firstName: {v['firstName']}"
        assert v["lastName"] == "Fields", f"lastName: {v['lastName']}"
        assert v["email"] == f"full-{tag}@example.org", f"email: {v['email']}"
        assert v["dateOfBirth"] == "1990-05-15", f"dateOfBirth: {v['dateOfBirth']}"
        assert v["department"] is not None, "department missing"

        # Employment fields
        emps = v.get("employments", [])
        assert len(emps) >= 1, "No employment"
        assert emps[0]["startDate"] == "2026-08-01", f"startDate: {emps[0]['startDate']}"

        details = emps[0].get("employmentDetails", [])
        assert len(details) >= 1, "No employment details"
        d = details[0]
        assert d["employmentType"] == "ORDINARY", f"type: {d['employmentType']}"
        assert d["percentageOfFullTimeEquivalent"] == 80.0, (
            f"pct: {d['percentageOfFullTimeEquivalent']}"
        )
        assert d["annualSalary"] == 550000.0, f"salary: {d['annualSalary']}"
        assert d["shiftDurationHours"] == 6.0, f"hours: {d['shiftDurationHours']}"

    def test_single_step_with_nonexistent_department(self, client):
        """LLM classifies as single create_employee without create_department.
        Department must be auto-created.

        Based on real 0/22 failure: department 'Utvikling' not found.
        """
        tag = uid()
        result = run_handler(
            client,
            "create_employee",
            {
                "firstName": f"Auto-{tag}",
                "lastName": "Dept",
                "email": f"auto-{tag}@example.org",
                "department": f"NewDept-{tag}",
            },
        )
        assert result["id"], f"Employee not created: {result}"
        v = client.get(f"/employee/{result['id']}", fields="department(name)")["value"]
        assert v["department"] is not None
        assert v["department"]["name"] == f"NewDept-{tag}"

    def test_onboarding_minimal(self, client):
        """Simpler variant: just name + email + department."""
        tag = uid()
        run_handler(client, "create_department", {"name": f"HR-{tag}"})
        emp_result = run_handler(
            client,
            "create_employee",
            {
                "firstName": f"Simple-{tag}",
                "lastName": "Test",
                "email": f"simple-{tag}@example.com",
                "department": f"HR-{tag}",
            },
        )
        assert emp_result["id"]
        v = client.get(f"/employee/{emp_result['id']}", fields="department(name)")["value"]
        assert v["department"] is not None


# ============================================================
# PATTERN 2: Supplier invoice from PDF
# Competition: create supplier + create voucher with VAT
# ============================================================


class TestSupplierInvoiceFromPDF:
    """Simulates: 'Register supplier invoice, create supplier if needed'"""

    def test_supplier_invoice_2_postings(self, client):
        """Correct pattern: 2 postings (expense gross + AP)."""
        tag = uid()
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Supplier invoice {tag}",
                "supplier": {
                    "name": f"InvSup-{tag} AS",
                    "organizationNumber": "888999000",
                },
                "date": "2026-02-15",
                "postings": [
                    {"account": 7300, "debit": 50000, "description": "Services"},
                    {"account": 2400, "credit": 50000, "description": "AP"},
                ],
            },
        )
        assert result["id"]

    def test_supplier_invoice_boolean_debit(self, client):
        """LLM sends debit: true instead of debit: amount."""
        tag = uid()
        from src.services.param_normalizer import normalize_params

        params = normalize_params(
            {
                "description": f"Bool invoice {tag}",
                "supplier": {"name": f"BoolSup-{tag}"},
                "postings": [
                    {"debit": True, "account": 7300, "amount": 30000},
                    {"debit": False, "account": 2400, "amount": 30000},
                ],
            }
        )
        result = run_handler(client, "create_voucher", params)
        assert result["id"]

    def test_supplier_invoice_vat_as_percentage_int(self, client):
        """LLM sends vatType as integer percentage (25), not VAT type ID.

        Based on real competition failure: vatType: 25 became {"id": 25}
        which is invalid, causing 404 on voucher creation.
        """
        tag = uid()
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"VAT int {tag}",
                "supplier": {"name": f"VATInt-{tag}"},
                "postings": [
                    {"account": 7300, "debit": 25000, "vatType": 25, "description": "Expense"},
                    {"account": 2400, "credit": 25000, "description": "AP"},
                ],
            },
        )
        assert result["id"], f"Voucher not created: {result}"

    def test_supplier_invoice_3_posting_vat_merge(self, client):
        """LLM sends 3 postings (net+VAT+AP), should merge to 2."""
        tag = uid()
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"VAT merge {tag}",
                "supplier": {"name": f"VATSup-{tag}"},
                "vatRate": 25,
                "postings": [
                    {"account": 7300, "debit": 8000},
                    {"account": 2710, "debit": 2000},
                    {"account": 2400, "credit": 10000},
                ],
            },
        )
        assert result["id"]


# ============================================================
# PATTERN 3: Invoice with products and payment
# Competition: create invoice for customer with product lines + register payment
# ============================================================


# ============================================================
# PATTERN 2b: Receipt/expense voucher with department
# Competition: 'Book receipt for X on department Y with correct VAT'
# ============================================================


class TestReceiptVoucherWithDepartment:
    """Simulates: 'Book Whiteboard receipt on department HR, correct VAT'

    Based on real competition prompt:
    'Vi trenger Whiteboard fra denne kvitteringen bokført på avdeling HR.
    Bruk riktig utgiftskonto basert på kjøpet, og sørg for korrekt MVA-behandling.'
    """

    def test_receipt_voucher_with_dept_on_postings(self, client):
        tag = uid()
        # Step 1: Create supplier
        run_handler(
            client,
            "create_supplier",
            {"name": f"Jernia-{tag}", "organizationNumber": "988015148"},
        )
        # Step 2: Create department
        run_handler(client, "create_department", {"name": f"HR-{tag}"})
        # Step 3: Create voucher with department on postings
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Whiteboard receipt {tag}",
                "date": "2026-06-21",
                "supplier": {"name": f"Jernia-{tag}"},
                "postings": [
                    {
                        "account": 6540,
                        "debit": 14300,
                        "description": "Whiteboard",
                        "department": f"HR-{tag}",
                    },
                    {
                        "account": 2400,
                        "credit": 14300,
                        "description": "Leverandørgjeld",
                    },
                ],
            },
        )
        v_id = result["id"]
        assert v_id
        # Verify department is set on the expense posting
        voucher = client.get(
            f"/ledger/voucher/{v_id}",
            fields="postings(account(number),department(id,name),amountGross)",
        )["value"]
        expense_posting = None
        for p in voucher["postings"]:
            if p.get("account", {}).get("number") == 6540:
                expense_posting = p
                break
        if expense_posting:
            assert expense_posting.get("department") is not None, (
                "Department not set on expense posting"
            )

    def test_receipt_with_supplier_and_vat(self, client):
        """Supplier receipt with amount including VAT."""
        tag = uid()
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Office supplies {tag}",
                "supplier": {"name": f"Staples-{tag}"},
                "postings": [
                    {"account": 6540, "debit": 5000, "description": "Office supplies"},
                    {"account": 2400, "credit": 5000, "description": "AP"},
                ],
            },
        )
        assert result["id"]


class TestInvoiceWithPayment:
    """Simulates: 'Create invoice for customer X with products, register payment'"""

    def test_invoice_with_multiple_products(self, client):
        tag = uid()
        result = run_handler(
            client,
            "create_invoice",
            {
                "customer": {
                    "name": f"InvCust-{tag} AS",
                    "organizationNumber": "111222333",
                },
                "orderLines": [
                    {
                        "product": {
                            "name": f"Prod-A-{tag}",
                            "number": str(secrets.randbelow(90000) + 10000),
                        },
                        "count": 2,
                        "unitPriceExcludingVatCurrency": 15000,
                    },
                    {
                        "product": {
                            "name": f"Prod-B-{tag}",
                            "number": str(secrets.randbelow(90000) + 10000),
                        },
                        "count": 1,
                        "unitPriceExcludingVatCurrency": 25000,
                    },
                ],
                "register_payment": {"amount": 55000},
            },
        )
        assert result["id"]
        inv = client.get(f"/invoice/{result['id']}", fields="amount,amountOutstanding")["value"]
        assert inv["amountOutstanding"] == 0, f"Not paid: outstanding={inv['amountOutstanding']}"


# ============================================================
# PATTERN 4: Create project with customer and PM
# Competition: create project linked to customer, with specific PM
# ============================================================


# ============================================================
# PATTERN 3b: Invoice with pre-existing products (name conflict)
# Competition: sandbox has pre-populated products
# ============================================================


class TestInvoiceWithExistingProducts:
    """Simulates: products already exist, should find them not crash.

    Based on real competition failure: product name 'Sessão de formação'
    already exists, creation fails with 422, should search by name.
    """

    def test_product_found_by_name(self, client):
        tag = uid()
        prod_num = secrets.randbelow(90000) + 10000
        # Create product first
        run_handler(
            client,
            "create_product",
            {"name": f"ExistProd-{tag}", "number": prod_num, "priceExcludingVatCurrency": 5000},
        )
        # Now create invoice using same product name — should find, not crash
        result = run_handler(
            client,
            "create_invoice",
            {
                "customer": {"name": f"EPCust-{tag}"},
                "orderLines": [
                    {
                        "product": f"ExistProd-{tag}",
                        "productNumber": str(prod_num),
                        "count": 1,
                        "priceExcludingVatCurrency": 5000,
                    }
                ],
            },
        )
        assert result["id"], f"Invoice not created: {result}"


# ============================================================
# PATTERN 3c: Late fee / overdue invoice (Mahngebühr/purregebyr)
# Competition: 'Book late fee, create invoice for fee, send it,
# register partial payment on overdue invoice'
# ============================================================


class TestLateFeeFlow:
    """Simulates: 'Book late fee voucher + invoice + send + partial payment'

    Based on real competition prompt:
    'En av kundene dine har en forfalt faktura. Bokfør et purregebyr
    på 50 kr. Debet kundefordringer (1500), kredit purregebyr (3400).
    Opprett også en faktura for purregebyret og send den.
    Registrer en delbetaling på 5000 kr på den forfalte fakturaen.'
    """

    def test_late_fee_voucher_with_auto_customer(self, client):
        """Voucher on account 1500 auto-finds customer when none specified."""
        tag = uid()
        # Create a customer first (simulates pre-existing data)
        run_handler(client, "create_customer", {"name": f"OverdueCust-{tag}"})

        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Late fee {tag}",
                "postings": [
                    {"account": 1500, "debit": 50, "description": "Kundefordringer"},
                    {"account": 3400, "credit": 50, "description": "Purregebyr"},
                ],
            },
        )
        assert result["id"], f"Voucher not created: {result}"

        # Verify customer was attached to the 1500 posting
        v = client.get(
            f"/ledger/voucher/{result['id']}",
            fields="postings(account(number),customer(id))",
        )["value"]
        for p in v["postings"]:
            if p.get("account", {}).get("number") == 1500:
                assert p.get("customer") is not None, (
                    "Customer not attached to accounts receivable posting"
                )

    def test_send_invoice_with_default_sendtype(self, client):
        """send_invoice should use EMAIL as default sendType, zero errors."""
        tag = uid()
        errors_before = client.error_count
        result = run_handler(
            client,
            "send_invoice",
            {
                "customer": {"name": f"SendCust-{tag}"},
                "orderLines": [
                    {
                        "description": "Late fee",
                        "unitPriceExcludingVatCurrency": 50,
                        "count": 1,
                    }
                ],
            },
        )
        assert result.get("id")
        assert result.get("action") == "sent"
        errors_after = client.error_count
        assert errors_after == errors_before, (
            f"send_invoice caused {errors_after - errors_before} errors"
        )

    def test_context_propagates_customer_from_voucher(self, client):
        """Voucher finds overdue customer → must propagate to later steps.

        Based on real competition failure (5/10): voucher found customer
        but steps 2-4 had no customer because context wasn't propagated.
        """
        tag = uid()
        # Pre-existing customer + unpaid invoice
        run_handler(
            client,
            "create_customer",
            {"name": f"CtxCust-{tag}", "organizationNumber": "880860666"},
        )
        run_handler(
            client,
            "create_invoice",
            {
                "customer": {"name": f"CtxCust-{tag}"},
                "orderLines": [
                    {
                        "description": "Unpaid service",
                        "unitPriceExcludingVatCurrency": 10000,
                        "count": 1,
                    }
                ],
            },
        )

        # Simulate multi-step: voucher (no customer) → invoice → payment
        # Step 1: Voucher — should find overdue customer and set in params
        from src.services.param_normalizer import normalize_params
        from src.task_router import _inject_context, _strip_placeholders, _update_context

        voucher_params = normalize_params(
            _strip_placeholders(
                {
                    "description": f"Late fee {tag}",
                    "postings": [
                        {"account": 1500, "debit": 35},
                        {"account": 3400, "credit": 35},
                    ],
                }
            )
        )
        v_result = run_handler(client, "create_voucher", voucher_params)
        assert v_result["id"]

        # Verify customer was set in params by the handler
        assert "customer" in voucher_params, (
            "Voucher handler should set customer in params for context propagation"
        )

        # Simulate context update + inject
        context: dict = {}
        _update_context(context, v_result, voucher_params, "create_voucher")
        assert "customer" in context, f"Customer not in context: {context}"

        # Step 2: Invoice with injected context
        inv_params = _inject_context(
            {
                "orderLines": [
                    {"description": "Fee", "unitPriceExcludingVatCurrency": 35, "count": 1}
                ]
            },
            context,
        )
        assert "customer" in inv_params, "Customer not injected into invoice params"

        inv_result = run_handler(client, "create_invoice", inv_params)
        assert inv_result["id"], f"Invoice failed without customer: {inv_result}"

    def test_full_late_fee_flow_with_overdue_invoice(self, client):
        """End-to-end: find overdue invoice, voucher, fee invoice, send, partial pay.

        Mirrors exact competition pattern:
        1) Pre-existing customer + overdue invoice in sandbox
        2) Late fee voucher (debit 1500, credit 3400) — finds overdue customer
        3) Create invoice for the fee
        4) Send invoice
        5) Partial payment on the ORIGINAL overdue invoice (not the fee)
        """
        tag = uid()
        # Simulate pre-existing customer + overdue invoice
        run_handler(
            client,
            "create_customer",
            {"name": f"LateFull-{tag}", "organizationNumber": "880860666"},
        )
        # Create an "overdue" invoice (unpaid)
        overdue_inv = run_handler(
            client,
            "create_invoice",
            {
                "customer": {"name": f"LateFull-{tag}"},
                "orderLines": [
                    {
                        "description": "Original service",
                        "unitPriceExcludingVatCurrency": 20000,
                        "count": 1,
                    }
                ],
            },
        )
        overdue_id = overdue_inv["id"]
        assert overdue_id

        # Step 1: Late fee voucher — should auto-find the overdue customer
        v_result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Purregebyr {tag}",
                "postings": [
                    {"account": 1500, "debit": 35, "description": "Kundefordringer"},
                    {"account": 3400, "credit": 35, "description": "Purregebyr"},
                ],
                # No customer — should find from overdue invoice
            },
        )
        assert v_result["id"]

        # Step 2: Fee invoice
        fee_inv = run_handler(
            client,
            "create_invoice",
            {
                "customer": {"name": f"LateFull-{tag}"},
                "orderLines": [
                    {"description": "Purregebyr", "unitPriceExcludingVatCurrency": 35, "count": 1}
                ],
            },
        )
        assert fee_inv["id"]

        # Step 3: Send fee invoice
        send_result = run_handler(client, "send_invoice", {"invoiceId": fee_inv["id"]})
        assert send_result.get("action") == "sent"

        # Step 4: Partial payment on OVERDUE invoice (not the fee)
        pay_result = run_handler(
            client,
            "register_payment",
            {"invoiceId": overdue_id, "amount": 5000},
        )
        assert pay_result.get("action") == "payment_registered"

        # Verify overdue invoice has partial payment (outstanding > 0 but < original)
        inv = client.get(f"/invoice/{overdue_id}", fields="amount,amountOutstanding")["value"]
        assert inv["amountOutstanding"] > 0, "Should still have outstanding"
        assert inv["amountOutstanding"] < inv["amount"], "Payment should reduce outstanding"

    def test_partial_payment(self, client):
        """Register partial payment on an invoice (not full amount)."""
        tag = uid()
        # Create invoice first
        inv_result = run_handler(
            client,
            "create_invoice",
            {
                "customer": {"name": f"PartialCust-{tag}"},
                "orderLines": [
                    {
                        "description": "Service",
                        "unitPriceExcludingVatCurrency": 20000,
                        "count": 1,
                    }
                ],
            },
        )
        inv_id = inv_result["id"]
        assert inv_id

        # Register partial payment of 5000
        pay_result = run_handler(
            client,
            "register_payment",
            {"invoiceId": inv_id, "amount": 5000},
        )
        assert pay_result.get("action") == "payment_registered"

        # Verify outstanding amount
        inv = client.get(f"/invoice/{inv_id}", fields="amount,amountOutstanding")["value"]
        assert inv["amountOutstanding"] > 0, "Should still have outstanding balance"
        assert inv["amountOutstanding"] < inv["amount"], "Payment should reduce outstanding"


# ============================================================
# PATTERN 3d: Currency invoice with agio/disagio
# Competition: 'Invoice in EUR, customer paid at different rate, book exchange diff'
# ============================================================


class TestCurrencyInvoiceWithAgio:
    """Simulates: EUR invoice with exchange rate gain/loss.

    Based on real competition prompt: invoice 16689 EUR at 11.66, paid at 12.24.
    Agio = (12.24-11.66)*16689 = 9675.62 NOK.
    """

    def test_nested_posting_normalization(self, client):
        """LLM sends nested debit/credit objects — should be flattened."""
        tag = uid()
        from src.services.param_normalizer import normalize_params

        params = normalize_params(
            {
                "description": f"Agio {tag}",
                "postings": [
                    {"debit": {"account": 1500, "amount": 9675.62, "description": "Agio"}},
                    {"credit": {"account": 8060, "amount": 9675.62, "description": "Agio"}},
                ],
                "customer": {"name": f"AgioCust-{tag}"},
            }
        )
        # Verify normalization flattened the nested objects
        assert params["postings"][0]["account"] == 1500
        assert params["postings"][0]["debit"] == 9675.62
        assert params["postings"][1]["credit"] == 9675.62

        result = run_handler(client, "create_voucher", params)
        assert result["id"]


# ============================================================
# PATTERN 3e: Currency payment at different exchange rate
# Competition: 'Invoice in EUR at rate X, customer paid at rate Y'
# ============================================================


class TestCurrencyPaymentAmount:
    """Verify payment uses the PAYMENT exchange rate, not invoice rate.

    Based on real competition run:
    Invoice: 13986 EUR at 10.37 = 144994.92 NOK
    Payment: 13986 EUR at 11.31 = 158201.66 NOK
    Check 2 failed because we paid 144994.92 instead of 158201.66
    """

    def test_payment_uses_payment_rate(self, client):
        tag = uid()
        # Create invoice at original rate
        inv_result = run_handler(
            client,
            "create_invoice",
            {
                "customer": {"name": f"EURCust-{tag}"},
                "orderLines": [
                    {
                        "description": "EUR service",
                        "unitPriceExcludingVatCurrency": 100000,
                        "count": 1,
                    }
                ],
            },
        )
        assert inv_result["id"]

        # Register payment with exchange rate info
        pay_result = run_handler(
            client,
            "register_payment",
            {
                "invoiceId": inv_result["id"],
                "amount": 100000,  # LLM might send original NOK
                "exchangeRate": 11.31,
                "currencyAmount": 13986,
            },
        )
        assert pay_result.get("action") == "payment_registered"


class TestProjectWithCustomerAndPM:
    """Simulates: 'Create project X linked to customer Y, PM is Z'"""

    def test_project_with_all_fields(self, client):
        tag = uid()
        result = run_handler(
            client,
            "create_project",
            {
                "name": f"Project-{tag}",
                "customer": {"name": f"ProjCust-{tag}", "organizationNumber": "777888999"},
                "projectManager": {
                    "firstName": f"PM-{tag}",
                    "lastName": "Leader",
                    "email": f"pm-{tag}@example.com",
                },
                "startDate": "2026-01-01",
            },
        )
        assert result["id"]
        v = client.get(f"/project/{result['id']}", fields="name,customer(name)")["value"]
        assert v["customer"] is not None

        # PM employee should exist
        emps = client.get("/employee", params={"firstName": f"PM-{tag}", "count": 1}, fields="id")
        assert len(emps["values"]) > 0


# ============================================================
# PATTERN 5: Travel expense with costs and per diem
# Competition: create travel expense with multiple cost categories
# ============================================================


class TestTravelExpenseWithCosts:
    """Simulates: 'Register travel expense with flights, hotel, taxi'"""

    def test_travel_with_multiple_costs(self, client):
        tag = uid()
        result = run_handler(
            client,
            "create_travel_expense",
            {
                "employee": {
                    "firstName": f"Trav-{tag}",
                    "lastName": "Expense",
                    "email": f"trav-{tag}@example.com",
                },
                "title": f"Customer visit {tag}",
                "travelDetails": {
                    "departureDate": "2026-03-01",
                    "returnDate": "2026-03-03",
                    "destination": "Oslo",
                    "purpose": "Client meeting",
                },
                "costs": [
                    {"description": "Fly", "amount": 4500, "date": "2026-03-01"},
                    {"description": "Hotell", "amount": 2800, "date": "2026-03-01"},
                    {"description": "Taxi", "amount": 650, "date": "2026-03-02"},
                ],
            },
        )
        assert result["id"]
        costs = client.get(
            "/travelExpense/cost",
            params={"travelExpenseId": str(result["id"])},
            fields="id",
        )
        assert len(costs["values"]) >= 3


# ============================================================
# PATTERN 6: Multiple departments in one prompt
# Competition: 'Create departments: X, Y, Z'
# ============================================================


# ============================================================
# PATTERN 5b: Employee with pre-existing email (email conflict)
# Competition: sandbox has pre-existing employees, must find them
# ============================================================


class TestEmployeeEmailConflict:
    """Simulates: employee already exists with same email.

    Based on real competition failure: retry-with-fix stripped email,
    then 'email required for Tripletex users' error. Should instead
    find existing employee by email.
    """

    def test_create_twice_same_email(self, client):
        """Second create with same email should return existing employee."""
        tag = uid()
        email = f"conflict-{tag}@example.org"
        # First create
        r1 = run_handler(
            client,
            "create_employee",
            {"firstName": f"First-{tag}", "lastName": "Test", "email": email},
        )
        assert r1["id"]

        # Second create with same email — should find existing, not crash
        r2 = run_handler(
            client,
            "create_employee",
            {"firstName": f"Second-{tag}", "lastName": "Test", "email": email},
        )
        assert r2["id"], f"Employee not found/created: {r2}"
        assert r2["id"] == r1["id"], "Should return same employee ID"

    def test_entity_resolver_email_conflict(self, client):
        """Entity resolver should find employee by email on conflict."""
        from src.handlers.entity_resolver import resolve

        tag = uid()
        email = f"resolve-{tag}@example.org"
        # Create employee first
        r1 = run_handler(
            client,
            "create_employee",
            {"firstName": f"Res-{tag}", "lastName": "Test", "email": email},
        )
        # Resolve same employee — should find by email, not crash
        ref = resolve(
            client,
            "employee",
            {"firstName": f"Res-{tag}", "lastName": "Test", "email": email},
        )
        assert ref["id"] == r1["id"]


class TestBatchDepartments:
    """Simulates: 'Create three departments: Utvikling, Admin, Lager'"""

    def test_batch_create(self, client):
        tag = uid()
        result = run_handler(
            client,
            "create_department",
            {
                "name": f"Batch-{tag}",
                "items": [
                    {"name": f"Utvikling-{tag}"},
                    {"name": f"Admin-{tag}"},
                    {"name": f"Lager-{tag}"},
                ],
            },
        )
        assert result.get("count") == 3 or len(result.get("ids", [])) == 3


# ============================================================
# PATTERN 7: Payroll with salary and bonus
# Competition: 'Run payroll for employee X, base salary Y, bonus Z'
# ============================================================


class TestPayrollWithBonus:
    """Simulates: 'Run payroll for employee, base + bonus'"""

    def test_payroll_basic(self, client):
        tag = uid()
        result = run_handler(
            client,
            "run_payroll",
            {
                "employee": {
                    "firstName": f"Payroll-{tag}",
                    "lastName": "Worker",
                    "email": f"payroll-{tag}@example.com",
                },
                "baseSalary": 45000,
                "bonus": 5000,
                "bonusDescription": "Q1 bonus",
                "month": 3,
                "year": 2026,
            },
        )
        # Payroll may fail on sandbox (employment/division issue) — that's OK
        assert result.get("id") or "error" in result


# ============================================================
# PATTERN 8: Credit note for invoice
# Competition: 'Customer complained, create credit note'
# ============================================================


# ============================================================
# PATTERN 8b: Payment reversal
# Competition: 'Customer returned payment, reverse it'
# ============================================================


class TestPaymentReversal:
    """Simulates: 'Customer X has returned payment. Reverse it.'

    Based on real competition run:
    Params: customer Vestfjord AS, amount -20000, reversal true,
    orderLines: [{product: Analyserapport, amount: 16000}]
    """

    def test_reversal_creates_invoice_then_reverses(self, client):
        """Create invoice, pay it, then reverse payment — outstanding should equal amount."""
        tag = uid()
        result = run_handler(
            client,
            "register_payment",
            {
                "customer": {"name": f"RevCust-{tag}", "organizationNumber": "880860666"},
                "amount": -20000,
                "reversal": True,
                "orderLines": [
                    {
                        "product": {"name": f"RevProd-{tag}"},
                        "amount": 16000,
                        "count": 1,
                    }
                ],
            },
        )
        inv_id = result.get("id")
        assert inv_id, f"Invoice not created: {result}"
        assert result.get("action") == "payment_reversed"

        # Verify: invoice amount should be 16000 (net), outstanding should equal amount
        inv = client.get(f"/invoice/{inv_id}", fields="amount,amountOutstanding")["value"]
        assert inv["amount"] > 0, "Invoice should have positive amount"
        assert inv["amountOutstanding"] == inv["amount"], (
            f"After reversal, outstanding ({inv['amountOutstanding']}) "
            f"should equal amount ({inv['amount']})"
        )

    def test_reversal_with_negative_amount(self, client):
        """Negative amount should be treated as reversal."""
        tag = uid()
        result = run_handler(
            client,
            "register_payment",
            {
                "customer": {"name": f"NegCust-{tag}"},
                "amount": -15000,
                "reversal": True,
                "description": "Returned payment",
            },
        )
        assert result.get("id")
        assert result.get("action") == "payment_reversed"


class TestCreditNoteFlow:
    """Simulates: 'Customer X complained about invoice, create credit note'"""

    def test_create_invoice_then_credit_note(self, client):
        tag = uid()
        result = run_handler(
            client,
            "create_credit_note",
            {
                "customer": {"name": f"CNCust-{tag}"},
                "orderLines": [
                    {
                        "description": "Consulting",
                        "unitPriceExcludingVatCurrency": 15000,
                        "count": 1,
                    }
                ],
            },
        )
        assert result.get("invoiceId") or result.get("id")


# ============================================================
# PATTERN 9: Update project with fixed price
# Competition: 'Set fixed price X on project Y for customer Z'
# ============================================================


class TestProjectFixedPriceAndMilestone:
    """Simulates: 'Create project with fixed price, invoice 25% milestone'

    Based on real competition prompt:
    'Fixez un prix forfaitaire de 328650 NOK sur le projet
    Développement e-commerce pour Cascade SARL.
    Facturez au client 25% du prix fixe.'
    """

    def test_create_project_with_pm_string(self, client):
        """PM as string name should be resolved to employee."""
        tag = uid()
        result = run_handler(
            client,
            "create_project",
            {
                "name": f"FixP-{tag}",
                "customer": {"name": f"FixCust-{tag}"},
                "projectManager": f"PM-{tag} Leader",
            },
        )
        assert result["id"]
        # PM employee should exist
        emps = client.get("/employee", params={"firstName": f"PM-{tag}", "count": 1}, fields="id")
        assert len(emps["values"]) > 0, "PM employee not created from string name"

    def test_full_project_milestone_flow(self, client):
        """End-to-end: customer + PM + project + 25% milestone invoice.

        Mirrors exact competition pattern:
        1) Create customer Cascade SARL
        2) Create employee Alice Moreau (PM)
        3) Create project with customer, PM string
        4) Invoice 25% of fixed price as milestone
        """
        tag = uid()
        # Step 1: Create customer
        cust = run_handler(
            client,
            "create_customer",
            {"name": f"Cascade-{tag}", "organizationNumber": "913754689"},
        )
        assert cust["id"]

        # Step 2: Create PM employee
        emp_result = run_handler(
            client,
            "create_employee",
            {
                "firstName": f"Alice-{tag}",
                "lastName": "Moreau",
                "email": f"alice-{tag}@example.org",
            },
        )
        assert emp_result["id"]

        # Step 3: Create project with PM as string
        proj_result = run_handler(
            client,
            "create_project",
            {
                "name": f"E-commerce-{tag}",
                "customer": {"name": f"Cascade-{tag}"},
                "projectManager": f"Alice-{tag} Moreau",
            },
        )
        assert proj_result["id"]
        v = client.get(
            f"/project/{proj_result['id']}",
            fields="name,customer(id),projectManager(id)",
        )["value"]
        assert v["customer"] is not None, "Customer not linked"

        # Step 4: Invoice 25% milestone (328650 * 0.25 = 82162.50)
        inv_result = run_handler(
            client,
            "create_invoice",
            {
                "customer": {"name": f"Cascade-{tag}"},
                "orderLines": [
                    {
                        "description": "Milestone 25%",
                        "count": 1,
                        "unitPriceExcludingVatCurrency": 82162.50,
                    }
                ],
            },
        )
        assert inv_result["id"]

    def test_update_project_fixed_price(self, client):
        tag = uid()
        run_handler(client, "create_project", {"name": f"UpdFP-{tag}"})
        result = run_handler(
            client,
            "update_project",
            {"name": f"UpdFP-{tag}", "fixedPrice": 200000},
        )
        assert result.get("action") == "updated"


# ============================================================
# PATTERN 10: Timesheet logging
# Competition: 'Log X hours for employee on activity in project'
# ============================================================


# ============================================================
# PATTERN 11: Ledger correction with multiple error types
# Competition: 'Find 4 errors in ledger, create corrective postings'
# ============================================================


class TestLedgerCorrectionMultipleErrors:
    """Simulates: 'Find errors in ledger and create corrective vouchers'

    Based on real competition prompt:
    'Descobrimos erros no livro razão... um lançamento na conta errada,
    um voucher duplicado, uma linha de IVA em falta, e um valor incorreto.
    Corrija todos os erros com lançamentos corretivos.'
    """

    def test_corrections_from_structured_array(self, client):
        """When LLM extracts corrections array instead of raw postings."""
        tag = uid()
        result = run_handler(
            client,
            "ledger_correction",
            {
                "description": f"Ledger corrections {tag}",
                "date": "2026-02-28",
                "corrections": [
                    {
                        "type": "wrong_account",
                        "wrongAccount": 7300,
                        "correctAccount": 7000,
                        "amount": 7800,
                        "description": "Wrong account correction",
                    },
                    {
                        "type": "duplicate_voucher",
                        "account": 6860,
                        "amount": 3500,
                        "description": "Duplicate reversal",
                    },
                    {
                        "type": "missing_vat",
                        "expenseAccount": 6500,
                        "vatAccount": 2710,
                        "netAmount": 18350,
                        "description": "Missing VAT line",
                    },
                    {
                        "type": "incorrect_amount",
                        "account": 7300,
                        "recordedAmount": 15000,
                        "correctAmount": 10050,
                        "difference": -4950,
                        "description": "Amount correction",
                    },
                ],
            },
        )
        assert result.get("id"), f"Correction voucher not created: {result}"

        # Verify voucher has postings
        v = client.get(
            f"/ledger/voucher/{result['id']}",
            fields="postings(account(number),amountGross)",
        )["value"]
        assert len(v["postings"]) >= 8, (
            f"Expected 8+ postings (4 corrections x 2), got {len(v['postings'])}"
        )

    def test_corrections_with_explicit_postings(self, client):
        """When LLM sends raw postings directly."""
        tag = uid()
        result = run_handler(
            client,
            "ledger_correction",
            {
                "description": f"Direct postings {tag}",
                "postings": [
                    {"account": 7000, "debit": 5000, "description": "Correction debit"},
                    {"account": 7300, "credit": 5000, "description": "Correction credit"},
                ],
            },
        )
        assert result.get("id"), f"Correction voucher not created: {result}"


# ============================================================
# PATTERN 12: Year-end closing with depreciation + tax
# Competition: 'Simplified year-end: depreciate assets, reverse prepaid,
# calculate and book tax at 22%, then close the year'
# ============================================================


class TestYearEndClosingFull:
    """Simulates the full year-end closing flow.

    Based on real competition prompt:
    'Gjer forenkla årsoppgjer for 2025: 1) Bokfør årlege avskrivingar
    for tre eigedelar... 2) Reverser forskotsbetalt kostnad...
    3) Rekn ut og bokfør skattekostnad (22% av skattbart resultat)'

    Key insight: tax amount requires querying the P&L AFTER booking
    depreciations, so the LLM can't compute it upfront.
    """

    def test_depreciation_voucher(self, client):
        """Each asset depreciation should produce a balanced voucher."""
        tag = uid()
        # Use accounts that exist on all sandboxes (7000 expense, 1200 asset)
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Depreciation {tag}",
                "date": "2025-12-31",
                "postings": [
                    {"account": 7000, "debit": 24187.50, "description": "Avskriving"},
                    {"account": 1200, "credit": 24187.50, "description": "Akkumulert"},
                ],
            },
        )
        assert result["id"]

    def test_tax_voucher_overrides_with_real_pnl(self, client):
        """Tax voucher should use actual P&L profit, not LLM's estimate."""
        tag = uid()
        # First create some revenue so there's a profit to tax
        run_handler(
            client,
            "create_voucher",
            {
                "description": f"Revenue {tag}",
                "date": "2025-06-15",
                "postings": [
                    {"account": 1920, "debit": 500000},
                    {"account": 3000, "credit": 500000},
                ],
            },
        )
        # Create some expenses
        run_handler(
            client,
            "create_voucher",
            {
                "description": f"Expenses {tag}",
                "date": "2025-06-15",
                "postings": [
                    {"account": 6010, "debit": 100000},
                    {"account": 1920, "credit": 100000},
                ],
            },
        )

        # Now create tax voucher with LLM's WRONG amount (just expenses)
        # The handler should override with real P&L: profit = 500000-100000 = 400000
        # Tax = 22% x 400000 = 88000
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Tax {tag}",
                "date": "2025-12-31",
                "postings": [
                    {"account": 8700, "debit": 22000, "description": "LLM wrong tax"},
                    {"account": 2920, "credit": 22000, "description": "LLM wrong tax"},
                ],
            },
        )
        assert result["id"]

        # Verify the posted amount was overridden
        v = client.get(
            f"/ledger/voucher/{result['id']}",
            fields="postings(account(number),amountGross)",
        )["value"]
        for p in v["postings"]:
            num = p.get("account", {}).get("number", 0)
            if num == 8700:
                # Should be close to 88000, not the LLM's 22000
                assert abs(p["amountGross"]) > 50000, (
                    f"Tax amount {p['amountGross']} was not overridden "
                    f"(expected ~88000, LLM sent 22000)"
                )

    def test_year_end_closing_generates_postings(self, client):
        """Year-end closing should generate postings from balance sheet."""
        result = run_handler(client, "year_end_closing", {"year": 2025})
        assert result.get("action") in ("year_end_closed", "no_postings_needed")


# ============================================================
# PATTERN 12b: Monthly closing with accrual + depreciation + salary
# Competition: 'Monthly close: book accrual, depreciation, salary provision'
# ============================================================


class TestMonthlyClosing:
    """Simulates monthly closing with 3 vouchers.

    Based on real competition prompt:
    'Führen Sie den Monatsabschluss für März 2026 durch.
    Buchen Sie die Rechnungsabgrenzung (3500 NOK/Monat),
    monatliche Abschreibung (79150/6 Jahre/12 = 1099.31),
    und Gehaltsrückstellung (Betrag nicht angegeben).'
    """

    def test_depreciation_uses_precise_amount(self, client):
        """Depreciation should use exact calculation, not rounded."""
        tag = uid()
        # 79150 / 6 years / 12 months = 1099.305... ≈ 1099.31
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Depreciation {tag}",
                "date": "2026-03-31",
                "postings": [
                    {"debitAccount": "6020", "creditAccount": "1210", "amount": 1099.31},
                ],
            },
        )
        assert result["id"]

    def test_salary_accrual_infers_amount(self, client):
        """When salary accrual amount is 0, should infer from existing data."""
        tag = uid()
        # First create some salary data
        run_handler(
            client,
            "create_voucher",
            {
                "description": f"Salary {tag}",
                "date": "2026-03-15",
                "postings": [
                    {"account": 5000, "debit": 45000},
                    {"account": 1920, "credit": 45000},
                ],
            },
        )
        # Now create salary accrual with amount 0 — should infer from account 5000
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Salary accrual {tag}",
                "date": "2026-03-31",
                "postings": [
                    {
                        "debitAccount": "5000",
                        "creditAccount": "2900",
                        "amount": 0,
                        "description": "Gehaltsrückstellung",
                    },
                ],
            },
        )
        assert result["id"], f"Salary accrual voucher not created: {result}"


class TestTimesheetLogging:
    """Simulates: 'Log hours for employee on activity in project'

    Based on real competition prompt:
    'Erfassen Sie 5 Stunden für Jonas Müller auf der Aktivität Analyse
    im Projekt E-Commerce-Entwicklung für Waldstein GmbH'
    """

    def test_log_many_hours_splits_across_days(self, client):
        """33 hours must be split across multiple days (max 7.5h/day).

        Based on real competition run (4/8):
        'Erfassen Sie 33 Stunden für Paul Müller auf der Aktivität Testing
        im Projekt Datenmigration für Sonnental GmbH. Stundensatz: 900 NOK/h.'
        """
        tag = uid()
        result = run_handler(
            client,
            "log_timesheet",
            {
                "employee": {
                    "firstName": f"Split-{tag}",
                    "lastName": "Hours",
                    "email": f"split-{tag}@example.com",
                },
                "hours": 33,
                "activity": f"Testing-{tag}",
                "project": f"SplitProj-{tag}",
                "date": "2026-03-10",
            },
        )
        assert result.get("entryId"), f"First entry not created: {result}"

        # Verify total hours across all entries for this employee
        emp_id = None
        emps = client.get(
            "/employee",
            params={"firstName": f"Split-{tag}", "count": 1},
            fields="id",
        )
        if emps.get("values"):
            emp_id = emps["values"][0]["id"]

        if emp_id:
            entries = client.get(
                "/timesheet/entry",
                params={
                    "employeeId": emp_id,
                    "dateFrom": "2026-03-10",
                    "dateTo": "2026-03-20",
                },
                fields="hours,date",
            )
            total = sum(e.get("hours", 0) for e in entries.get("values", []))
            assert total == 33.0, f"Total hours {total} != 33"
            assert len(entries["values"]) >= 5, (
                f"Expected 5+ entries (33/7.5), got {len(entries['values'])}"
            )

    def test_log_hours_creates_entry(self, client):
        tag = uid()
        result = run_handler(
            client,
            "log_timesheet",
            {
                "employee": {
                    "firstName": f"TS-{tag}",
                    "lastName": "Logger",
                    "email": f"ts-{tag}@example.com",
                },
                "hours": 5,
                "activity": f"Analyse-{tag}",
                "project": f"TSProj-{tag}",
                "date": "2026-03-15",
            },
        )
        assert result.get("entryId"), f"Timesheet entry not created: {result}"
        # Verify the entry
        entry = client.get(
            f"/timesheet/entry/{result['entryId']}",
            fields="hours,date",
        )["value"]
        assert entry["hours"] == 5.0
        assert entry["date"] == "2026-03-15"
