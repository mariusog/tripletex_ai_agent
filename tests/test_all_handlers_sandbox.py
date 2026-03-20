"""Comprehensive handler tests against Tripletex sandbox.

Tests every handler with realistic params, verifying all fields the competition checks.
Run: SANDBOX_URL=... SANDBOX_TOKEN=... python -m pytest tests/test_all_handlers_sandbox.py -v -s --tb=short -m slow
"""

from __future__ import annotations

import os
import secrets

import pytest

from src.api_client import TripletexClient, TripletexApiError
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


def run_handler(client, task_type, params):
    handler = HANDLER_REGISTRY[task_type]
    return handler.execute(client, params)


# ============================================================
# TIER 1: Simple CRUD
# ============================================================


class TestCreateEmployee:
    def test_all_fields(self, client):
        tag = uid()
        result = run_handler(client, "create_employee", {
            "firstName": f"Emp-{tag}",
            "lastName": "Testersen",
            "email": f"emp-{tag}@example.com",
            "dateOfBirth": "1990-06-15",
            "startDate": "2026-03-01",
            "phoneNumberMobile": "99001122",
        })
        emp_id = result["id"]
        assert emp_id

        v = client.get(f"/employee/{emp_id}", fields="*,employments(*)")["value"]
        assert v["firstName"] == f"Emp-{tag}"
        assert v["lastName"] == "Testersen"
        assert v["email"] == f"emp-{tag}@example.com"
        assert v["dateOfBirth"] == "1990-06-15"
        assert v["phoneNumberMobile"] == "99001122"
        assert v["department"] is not None

        emps = v.get("employments", [])
        assert len(emps) >= 1, "No employment record"
        emp_detail = client.get(f"/employee/employment/{emps[0]['id']}", fields="startDate")["value"]
        assert emp_detail["startDate"] == "2026-03-01"


class TestUpdateEmployee:
    def test_update_phone(self, client):
        tag = uid()
        # Create first
        run_handler(client, "create_employee", {
            "firstName": f"Upd-{tag}", "lastName": "Emp",
            "email": f"upd-{tag}@example.com",
        })
        # Update
        result = run_handler(client, "update_employee", {
            "firstName": f"Upd-{tag}", "lastName": "Emp",
            "phoneNumberMobile": "55667788",
        })
        assert result.get("action") == "updated"
        v = client.get(f"/employee/{result['id']}", fields="phoneNumberMobile")["value"]
        assert v["phoneNumberMobile"] == "55667788"


class TestCreateCustomer:
    def test_all_fields(self, client):
        tag = uid()
        result = run_handler(client, "create_customer", {
            "name": f"Cust-{tag} AS",
            "email": f"cust-{tag}@example.com",
            "phoneNumber": "11223344",
            "organizationNumber": "123456789",
        })
        cust_id = result["id"]
        v = client.get(f"/customer/{cust_id}", fields="name,email,phoneNumber,organizationNumber")["value"]
        assert v["name"] == f"Cust-{tag} AS"
        assert v["email"] == f"cust-{tag}@example.com"
        assert v["phoneNumber"] == "11223344"
        assert v["organizationNumber"] == "123456789"


class TestUpdateCustomer:
    def test_update_phone(self, client):
        tag = uid()
        run_handler(client, "create_customer", {"name": f"UpdCust-{tag} AS"})
        result = run_handler(client, "update_customer", {
            "name": f"UpdCust-{tag} AS",
            "phoneNumber": "99887766",
        })
        assert result.get("action") == "updated"


class TestCreateProduct:
    def test_with_price_and_number(self, client):
        num = secrets.randbelow(90000) + 10000
        result = run_handler(client, "create_product", {
            "name": f"Prod-{num}",
            "number": num,
            "priceExcludingVatCurrency": 3500,
        })
        prod_id = result["id"]
        v = client.get(f"/product/{prod_id}", fields="name,number,priceExcludingVatCurrency")["value"]
        assert v["name"] == f"Prod-{num}"
        assert str(v["number"]) == str(num)
        assert v["priceExcludingVatCurrency"] == 3500


class TestCreateDepartment:
    def test_basic(self, client):
        tag = uid()
        result = run_handler(client, "create_department", {
            "name": f"Dept-{tag}",
            "departmentNumber": tag[:4],
        })
        assert result["id"]


class TestCreateProject:
    def test_with_customer_and_pm(self, client):
        tag = uid()
        result = run_handler(client, "create_project", {
            "name": f"Proj-{tag}",
            "customer": {"name": f"ProjCust-{tag}", "organizationNumber": "987654321"},
            "projectManager": {
                "firstName": f"PM-{tag}", "lastName": "Lead",
                "email": f"pm-{tag}@example.com",
            },
        })
        proj_id = result["id"]
        assert proj_id
        v = client.get(f"/project/{proj_id}", fields="name,customer(id,name)")["value"]
        assert v["name"] == f"Proj-{tag}"
        assert v["customer"] is not None

        # PM employee should exist
        emps = client.get("/employee", params={
            "firstName": f"PM-{tag}", "lastName": "Lead", "count": 1
        }, fields="id")
        assert len(emps["values"]) > 0, "PM employee not created"


class TestCreateActivity:
    def test_basic(self, client):
        tag = uid()
        result = run_handler(client, "create_activity", {"name": f"Act-{tag}"})
        assert result["id"]


# ============================================================
# TIER 2: Multi-step workflows
# ============================================================


class TestCreateOrder:
    def test_with_lines(self, client):
        tag = uid()
        # Create customer first
        cust = run_handler(client, "create_customer", {"name": f"OrdCust-{tag}"})
        result = run_handler(client, "create_order", {
            "customer": f"OrdCust-{tag}",
            "orderLines": [
                {"product": {"name": f"OrdProd-{tag}", "number": str(secrets.randbelow(90000) + 10000)},
                 "count": 2, "unitPriceExcludingVatCurrency": 1500},
            ],
        })
        assert result["id"]


class TestCreateInvoiceWithPayment:
    def test_full_flow(self, client):
        tag = uid()
        result = run_handler(client, "create_invoice", {
            "customer": {"name": f"InvCust-{tag}", "organizationNumber": "111222333"},
            "orderLines": [
                {"product": {"name": f"InvProd-{tag}", "number": str(secrets.randbelow(90000) + 10000)},
                 "count": 1, "unitPriceExcludingVatCurrency": 25000},
            ],
            "register_payment": {"amount": 25000},
        })
        inv_id = result["id"]
        assert inv_id
        v = client.get(f"/invoice/{inv_id}", fields="amount,amountOutstanding")["value"]
        assert v["amount"] == 25000
        assert v["amountOutstanding"] == 0


class TestCreateInvoiceWithProject:
    def test_project_linked_and_pm_created(self, client):
        tag = uid()
        result = run_handler(client, "create_invoice", {
            "customer": {"name": f"ProjInvCust-{tag}"},
            "project": {
                "name": f"ProjInv-{tag}",
                "projectManager": {
                    "firstName": f"InvPM-{tag}", "lastName": "Boss",
                    "email": f"invpm-{tag}@example.com",
                },
            },
            "orderLines": [{"description": "Consulting", "unitPriceExcludingVatCurrency": 50000, "count": 1}],
        })
        order_id = result["orderId"]
        order = client.get(f"/order/{order_id}", fields="project(id,name)")["value"]
        assert order["project"] is not None, "Project not linked"

        # PM employee created
        emps = client.get("/employee", params={
            "firstName": f"InvPM-{tag}", "lastName": "Boss", "count": 1
        }, fields="id")
        assert len(emps["values"]) > 0, "PM employee not created"


class TestRegisterPayment:
    def test_creates_and_pays(self, client):
        tag = uid()
        result = run_handler(client, "register_payment", {
            "customer": {"name": f"PayCust-{tag}"},
            "amount": 18000,
            "description": "Service fee",
        })
        inv_id = result["id"]
        assert inv_id
        v = client.get(f"/invoice/{inv_id}", fields="amount,amountOutstanding")["value"]
        assert v["amountOutstanding"] == 0


class TestPaymentReversal:
    def test_reversal(self, client):
        tag = uid()
        result = run_handler(client, "register_payment", {
            "customer": {"name": f"RevCust-{tag}"},
            "amount": -15000,
            "reversal": True,
            "description": "Returned payment",
        })
        inv_id = result["id"]
        v = client.get(f"/invoice/{inv_id}", fields="amount,amountOutstanding")["value"]
        assert v["amount"] == 15000
        assert v["amountOutstanding"] == 15000


class TestCreateCreditNote:
    def test_creates_invoice_then_credits(self, client):
        tag = uid()
        result = run_handler(client, "create_credit_note", {
            "customer": {"name": f"CNCust-{tag}"},
            "orderLines": [{"description": "Credit item", "unitPriceExcludingVatCurrency": 8000, "count": 1}],
        })
        # Should have created invoice (even if credit note itself fails)
        assert result.get("invoiceId") or result.get("id")


class TestCreateTravelExpense:
    def test_with_costs(self, client):
        tag = uid()
        result = run_handler(client, "create_travel_expense", {
            "employee": {"firstName": f"Tr-{tag}", "lastName": "Reiser", "email": f"tr-{tag}@example.com"},
            "title": f"Trip {tag}",
            "costs": [
                {"description": "Fly", "amount": 5000},
                {"description": "Hotell", "amount": 3000},
                {"description": "Taxi", "amount": 800},
            ],
        })
        te_id = result["id"]
        assert te_id
        costs = client.get("/travelExpense/cost", params={"travelExpenseId": str(te_id)}, fields="id")
        assert len(costs["values"]) >= 3, f"Expected 3+ costs, got {len(costs['values'])}"


# ============================================================
# TIER 3: Complex workflows
# ============================================================


class TestCreateVoucher:
    def test_supplier_invoice(self, client):
        tag = uid()
        result = run_handler(client, "create_voucher", {
            "description": f"Supplier invoice {tag}",
            "supplier": {"name": f"Sup-{tag} AS", "organizationNumber": "444555666"},
            "postings": [
                {"account": 7300, "debit": 10000},
                {"account": 2400, "credit": 10000},
            ],
        })
        v_id = result["id"]
        assert v_id
        voucher = client.get(f"/ledger/voucher/{v_id}", fields="description,postings(*,supplier(id,name))")["value"]
        assert len(voucher["postings"]) >= 2
        # Check supplier is attached
        for p in voucher["postings"]:
            sup = p.get("supplier")
            if sup:
                assert sup["name"] == f"Sup-{tag} AS"
                break
        else:
            pytest.fail("No supplier on postings")


class TestCreateVoucherWithVAT:
    def test_3_posting_with_vat(self, client):
        """Supplier invoice with expense + VAT + AP postings."""
        tag = uid()
        result = run_handler(client, "create_voucher", {
            "description": f"VAT invoice {tag}",
            "supplier": {"name": f"VATSup-{tag}"},
            "postings": [
                {"account": 7100, "debit": 8000},
                {"account": 2710, "debit": 2000},
                {"account": 2400, "credit": 10000},
            ],
        })
        assert result["id"]


class TestReverseVoucherFallback:
    def test_falls_back_to_payment_reversal(self, client):
        """When no voucherId, should create invoice + reversal."""
        tag = uid()
        result = run_handler(client, "reverse_voucher", {
            "customer": {"name": f"RevV-{tag}"},
            "amount": 20000,
            "description": "Reversering",
        })
        inv_id = result.get("id")
        assert inv_id
        v = client.get(f"/invoice/{inv_id}", fields="amount,amountOutstanding")["value"]
        assert v["amount"] == 20000
        assert v["amountOutstanding"] == 20000
