"""Integration tests against the Tripletex sandbox.

Run with: python -m pytest tests/test_integration_sandbox.py -v -s --tb=short -m slow
Requires SANDBOX_TOKEN and SANDBOX_URL env vars.
"""

from __future__ import annotations

import os
import secrets

import pytest

from src.api_client import TripletexClient

SANDBOX_URL = os.environ.get("SANDBOX_URL", "")
SANDBOX_TOKEN = os.environ.get("SANDBOX_TOKEN", "")

pytestmark = pytest.mark.slow


def have_sandbox() -> bool:
    return bool(SANDBOX_URL and SANDBOX_TOKEN)


def make_client() -> TripletexClient:
    return TripletexClient(SANDBOX_URL, SANDBOX_TOKEN)


def uid() -> str:
    return secrets.token_hex(4)


@pytest.fixture
def client():
    if not have_sandbox():
        pytest.skip("No sandbox credentials")
    c = make_client()
    yield c
    c.close()


class TestCreateEmployee:
    def test_full_employee_with_employment(self, client):
        from src.handlers import HANDLER_REGISTRY

        tag = uid()
        params = {
            "firstName": f"Integ-{tag}",
            "lastName": "Testersen",
            "email": f"integ-{tag}@example.com",
            "dateOfBirth": "1990-06-15",
            "startDate": "2026-03-01",
        }
        handler = HANDLER_REGISTRY["create_employee"]
        result = handler.execute(client, params)
        emp_id = result["id"]
        assert emp_id, "Employee not created"

        # Verify all fields
        emp = client.get(f"/employee/{emp_id}", fields="*,employments(*)")
        v = emp["value"]
        assert v["firstName"] == f"Integ-{tag}"
        assert v["lastName"] == "Testersen"
        assert v["email"] == f"integ-{tag}@example.com"
        assert v["dateOfBirth"] == "1990-06-15"
        # userType is write-only (returns null on read)
        assert v["department"] is not None

        # Employment
        emps = v.get("employments", [])
        assert len(emps) >= 1, "No employment created"
        emp_detail = client.get(f"/employee/employment/{emps[0]['id']}", fields="*")
        ev = emp_detail["value"]
        assert ev["startDate"] == "2026-03-01"


class TestCreateCustomer:
    def test_with_org_number(self, client):
        from src.handlers import HANDLER_REGISTRY

        tag = uid()
        params = {
            "name": f"Integ Kunde {tag} AS",
            "email": f"kunde-{tag}@example.com",
            "phoneNumber": "12345678",
            "organizationNumber": "123456789",
        }
        handler = HANDLER_REGISTRY["create_customer"]
        result = handler.execute(client, params)
        cust_id = result["id"]
        assert cust_id

        cust = client.get(f"/customer/{cust_id}", fields="*")
        v = cust["value"]
        assert v["name"] == f"Integ Kunde {tag} AS"
        assert v["email"] == f"kunde-{tag}@example.com"
        assert v["phoneNumber"] == "12345678"
        assert v["organizationNumber"] == "123456789"


class TestCreateProduct:
    def test_with_price_and_number(self, client):
        from src.handlers import HANDLER_REGISTRY

        num = secrets.randbelow(90000) + 10000
        params = {
            "name": f"Integ Produkt {num}",
            "number": num,
            "priceExcludingVatCurrency": 2500,
        }
        handler = HANDLER_REGISTRY["create_product"]
        result = handler.execute(client, params)
        prod_id = result["id"]
        assert prod_id

        prod = client.get(f"/product/{prod_id}", fields="*")
        v = prod["value"]
        assert v["name"] == f"Integ Produkt {num}"
        assert str(v["number"]) == str(num)
        assert v["priceExcludingVatCurrency"] == 2500


class TestCreateDepartment:
    def test_basic(self, client):
        from src.handlers import HANDLER_REGISTRY

        tag = uid()
        params = {"name": f"Integ Avd {tag}", "departmentNumber": tag[:4]}
        handler = HANDLER_REGISTRY["create_department"]
        result = handler.execute(client, params)
        assert result["id"]


class TestCreateProject:
    def test_with_customer_and_employee(self, client):
        from src.handlers import HANDLER_REGISTRY

        tag = uid()
        params = {
            "name": f"Integ Prosjekt {tag}",
            "customer": {"name": f"Integ ProjKunde {tag}", "organizationNumber": "987654321"},
            "projectManager": {
                "firstName": f"PM-{tag}",
                "lastName": "Leder",
                "email": f"pm-{tag}@example.com",
            },
        }
        handler = HANDLER_REGISTRY["create_project"]
        result = handler.execute(client, params)
        proj_id = result["id"]
        assert proj_id

        proj = client.get(
            f"/project/{proj_id}",
            fields="name,customer(id,name),projectManager(id,firstName)",
        )
        v = proj["value"]
        assert v["name"] == f"Integ Prosjekt {tag}"
        assert v["customer"] is not None
        assert v["customer"]["name"] == f"Integ ProjKunde {tag}"

        # Employee should exist
        emps = client.get(
            "/employee",
            params={"firstName": f"PM-{tag}", "lastName": "Leder", "count": 1},
            fields="id",
        )
        assert len(emps["values"]) > 0, "PM employee not created"


class TestCreateInvoiceWithPayment:
    def test_full_flow(self, client):
        from src.handlers import HANDLER_REGISTRY

        tag = uid()
        params = {
            "customer": {"name": f"Integ InvKunde {tag}", "organizationNumber": "111222333"},
            "orderLines": [
                {
                    "product": {
                        "name": f"Integ Prod A {tag}",
                        "number": str(secrets.randbelow(90000) + 10000),
                    },
                    "count": 1,
                    "unitPriceExcludingVatCurrency": 15000,
                },
                {
                    "product": {
                        "name": f"Integ Prod B {tag}",
                        "number": str(secrets.randbelow(90000) + 10000),
                    },
                    "count": 2,
                    "unitPriceExcludingVatCurrency": 7500,
                },
            ],
            "register_payment": {"amount": 30000},
        }
        handler = HANDLER_REGISTRY["create_invoice"]
        result = handler.execute(client, params)
        inv_id = result["id"]
        assert inv_id, "Invoice not created"

        inv = client.get(f"/invoice/{inv_id}", fields="amount,amountOutstanding,customer(id,name)")
        v = inv["value"]
        assert v["amount"] == 30000, f"Wrong amount: {v['amount']}"
        assert v["amountOutstanding"] == 0, f"Not fully paid: {v['amountOutstanding']}"
        assert v["customer"]["name"] == f"Integ InvKunde {tag}"


class TestCreateInvoiceWithProject:
    def test_project_linked(self, client):
        from src.handlers import HANDLER_REGISTRY

        tag = uid()
        params = {
            "customer": {"name": f"Integ ProjInv {tag}"},
            "project": {"name": f"Integ InvProj {tag}"},
            "orderLines": [
                {"description": "Consulting", "unitPriceExcludingVatCurrency": 50000, "count": 1},
            ],
        }
        handler = HANDLER_REGISTRY["create_invoice"]
        result = handler.execute(client, params)
        order_id = result["orderId"]
        assert order_id

        order = client.get(f"/order/{order_id}", fields="project(id,name)")
        proj = order["value"].get("project")
        assert proj is not None, "Project not linked to order"


class TestCreateVoucher:
    def test_supplier_invoice(self, client):
        from src.handlers import HANDLER_REGISTRY

        tag = uid()
        params = {
            "description": f"Leverandørfaktura {tag}",
            "supplier": {"name": f"Integ Leverandør {tag}", "organizationNumber": "444555666"},
            "postings": [
                {"account": 7300, "debit": 10000},
                {"account": 2400, "credit": 10000},
            ],
        }
        handler = HANDLER_REGISTRY["create_voucher"]
        result = handler.execute(client, params)
        v_id = result["id"]
        assert v_id, "Voucher not created"

        voucher = client.get(f"/ledger/voucher/{v_id}", fields="description,postings(*)")
        v = voucher["value"]
        assert len(v["postings"]) >= 2


class TestCreateTravelExpense:
    def test_with_costs(self, client):
        from src.handlers import HANDLER_REGISTRY

        tag = uid()
        params = {
            "employee": {
                "firstName": f"Reise-{tag}",
                "lastName": "Ansatt",
                "email": f"reise-{tag}@example.com",
            },
            "title": f"Reise {tag}",
            "costs": [
                {"description": "Fly", "amount": 5000},
                {"description": "Taxi", "amount": 800},
            ],
        }
        handler = HANDLER_REGISTRY["create_travel_expense"]
        result = handler.execute(client, params)
        te_id = result["id"]
        assert te_id, "Travel expense not created"

        # Verify costs were added
        costs = client.get(
            "/travelExpense/cost",
            params={"travelExpenseId": str(te_id)},
            fields="id,amountCurrencyIncVat",
        )
        assert len(costs["values"]) >= 2, f"Expected 2+ costs, got {len(costs['values'])}"


class TestRegisterPayment:
    def test_creates_invoice_and_pays(self, client):
        from src.handlers import HANDLER_REGISTRY

        tag = uid()
        params = {
            "customer": {"name": f"Integ Pay {tag}"},
            "amount": 25000,
            "description": "Betaling",
        }
        handler = HANDLER_REGISTRY["register_payment"]
        result = handler.execute(client, params)
        inv_id = result["id"]
        assert inv_id

        inv = client.get(f"/invoice/{inv_id}", fields="amount,amountOutstanding")
        v = inv["value"]
        assert v["amountOutstanding"] == 0


class TestPaymentReversal:
    def test_reversal_restores_outstanding(self, client):
        from src.handlers import HANDLER_REGISTRY

        tag = uid()
        params = {
            "customer": {"name": f"Integ Rev {tag}"},
            "amount": -20000,
            "reversal": True,
            "description": "Reversering",
        }
        handler = HANDLER_REGISTRY["register_payment"]
        result = handler.execute(client, params)
        inv_id = result["id"]
        assert inv_id

        inv = client.get(f"/invoice/{inv_id}", fields="amount,amountOutstanding")
        v = inv["value"]
        assert v["amount"] == 20000, f"Wrong amount: {v['amount']}"
        assert v["amountOutstanding"] == 20000, f"Should be outstanding: {v['amountOutstanding']}"
