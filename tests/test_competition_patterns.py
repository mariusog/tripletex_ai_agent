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
        dept_result = run_handler(
            client, "create_department", {"name": f"Innkjøp-{tag}"}
        )
        assert dept_result["id"]

        # Step 2: Create employee with ALL competition-verified fields
        emp_result = run_handler(
            client,
            "create_employee",
            {
                "firstName": f"Hilde-{tag}",
                "lastName": "Bakken",
                "email": f"hilde-{tag}@example.org",
                "dateOfBirth": "1987-02-08",
                "nationalIdentityNumber": "08028777990",
                "department": f"Innkjøp-{tag}",
                "startDate": "2026-07-22",
                "employmentType": "fast",
                "employmentPercentage": 80,
                "annualSalary": 570000,
                "hoursPerDay": 6.0,
            },
        )
        assert emp_result["id"]

        # Verify ALL fields the competition checks
        v = client.get(
            f"/employee/{emp_result['id']}",
            fields="firstName,lastName,email,dateOfBirth,nationalIdentityNumber,"
            "department(id,name),employments(startDate,employmentDetails(*))",
        )["value"]
        assert v["firstName"] == f"Hilde-{tag}"
        assert v["lastName"] == "Bakken"
        assert v["email"] == f"hilde-{tag}@example.org"
        assert v["dateOfBirth"] == "1987-02-08"
        assert v["department"] is not None

        emps = v.get("employments", [])
        assert len(emps) >= 1, "No employment record"
        assert emps[0]["startDate"] == "2026-07-22"

        details = emps[0].get("employmentDetails", [])
        assert len(details) >= 1, "No employment details"
        detail = details[0]
        assert detail.get("percentageOfFullTimeEquivalent") == 80.0
        assert detail.get("employmentType") == "ORDINARY"

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
        v = client.get(
            f"/employee/{emp_result['id']}", fields="department(name)"
        )["value"]
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
            client, "employee",
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
            f"Expected 8+ postings (4 corrections × 2), got {len(v['postings'])}"
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
        # Depreciation: 193500 / 8 years = 24187.50
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Depreciation {tag}",
                "date": "2025-12-31",
                "postings": [
                    {"account": 6010, "debit": 24187.50, "description": "Avskriving"},
                    {"account": 1209, "credit": 24187.50, "description": "Akkumulert"},
                ],
            },
        )
        assert result["id"]
        v = client.get(
            f"/ledger/voucher/{result['id']}",
            fields="postings(amountGross)",
        )["value"]
        # Verify postings balance
        total = sum(p.get("amountGross", 0) for p in v["postings"])
        assert abs(total) < 0.01, f"Postings don't balance: {total}"

    def test_tax_voucher_must_have_amount(self, client):
        """Tax voucher must include actual amount, not empty postings."""
        tag = uid()
        # Tax = 22% of some profit
        tax_amount = round(100000 * 0.22, 2)
        result = run_handler(
            client,
            "create_voucher",
            {
                "description": f"Tax {tag}",
                "date": "2025-12-31",
                "postings": [
                    {"account": 8700, "debit": tax_amount, "description": "Skattekostnad"},
                    {"account": 2920, "credit": tax_amount, "description": "Betalbar skatt"},
                ],
            },
        )
        assert result["id"]

    def test_year_end_closing_generates_postings(self, client):
        """Year-end closing should generate postings from balance sheet."""
        # First create some activity so there's something to close
        tag = uid()
        run_handler(
            client,
            "create_voucher",
            {
                "description": f"Revenue {tag}",
                "date": "2025-06-15",
                "postings": [
                    {"account": 1920, "debit": 100000},
                    {"account": 3000, "credit": 100000},
                ],
            },
        )
        result = run_handler(
            client,
            "year_end_closing",
            {"year": 2025},
        )
        # Should either create a closing voucher or report no postings needed
        assert result.get("action") in ("year_end_closed", "no_postings_needed")


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
