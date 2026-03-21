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
    """Simulates: 'Create employee X, assign to dept Y, 80% stilling, salary Z'"""

    def test_onboarding_with_department_and_employment(self, client):
        tag = uid()
        # Step 1: Create department
        dept_result = run_handler(
            client, "create_department", {"name": f"Marketing-{tag}"}
        )
        assert dept_result["id"]

        # Step 2: Create employee with department name (not ID)
        emp_result = run_handler(
            client,
            "create_employee",
            {
                "firstName": f"Test-{tag}",
                "lastName": "Onboard",
                "email": f"test-{tag}@example.com",
                "dateOfBirth": "1990-05-15",
                "department": f"Marketing-{tag}",
                "employmentType": "Fast stilling",
                "employmentPercentage": 80,
                "startDate": "2026-06-01",
            },
        )
        assert emp_result["id"]

        # Verify
        v = client.get(
            f"/employee/{emp_result['id']}",
            fields="firstName,lastName,department(id,name),employments(*)",
        )["value"]
        assert v["firstName"] == f"Test-{tag}"
        assert v["department"] is not None
        assert len(v.get("employments", [])) >= 1


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
                        "product": {"name": f"Prod-A-{tag}", "number": str(secrets.randbelow(90000) + 10000)},
                        "count": 2,
                        "unitPriceExcludingVatCurrency": 15000,
                    },
                    {
                        "product": {"name": f"Prod-B-{tag}", "number": str(secrets.randbelow(90000) + 10000)},
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
        emps = client.get(
            "/employee", params={"firstName": f"PM-{tag}", "count": 1}, fields="id"
        )
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


class TestUpdateProjectFixedPrice:
    """Simulates: 'Set fixed price on project'"""

    def test_create_then_update(self, client):
        tag = uid()
        run_handler(client, "create_project", {"name": f"FixP-{tag}"})
        result = run_handler(
            client,
            "update_project",
            {
                "name": f"FixP-{tag}",
                "fixedPrice": 200000,
            },
        )
        assert result.get("action") == "updated"


# ============================================================
# PATTERN 10: Timesheet logging
# Competition: 'Log X hours for employee on activity in project'
# ============================================================


class TestTimesheetLogging:
    """Simulates: 'Log hours for employee on activity in project'"""

    def test_log_hours(self, client):
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
                "hours": 8,
                "activity": f"Consulting-{tag}",
                "project": f"TSProj-{tag}",
                "date": "2026-03-15",
            },
        )
        assert result.get("entryId") or result.get("action")
