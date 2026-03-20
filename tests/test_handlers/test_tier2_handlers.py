"""Tests for Tier 2 handlers: order, invoice, payment, credit note."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.handlers.base import get_handler
from tests.conftest import sample_api_response
from tests.test_handlers.conftest import make_invoice


def _mock_client(
    get_response: dict[str, Any] | None = None,
    post_response: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock TripletexClient with canned responses."""
    client = MagicMock()
    client.get.return_value = get_response or sample_api_response(values=[])
    client.post.return_value = post_response or sample_api_response(value={"id": 1})
    return client


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestTier2Registration:
    def _ensure_imported(self) -> None:
        import src.handlers  # noqa: F401

    def test_order_handler_registered(self):
        self._ensure_imported()
        assert get_handler("create_order") is not None

    def test_invoice_handler_registered(self):
        self._ensure_imported()
        assert get_handler("create_invoice") is not None

    def test_send_invoice_handler_registered(self):
        self._ensure_imported()
        assert get_handler("send_invoice") is not None

    def test_payment_handler_registered(self):
        self._ensure_imported()
        assert get_handler("register_payment") is not None

    def test_credit_note_handler_registered(self):
        self._ensure_imported()
        assert get_handler("create_credit_note") is not None


# ---------------------------------------------------------------------------
# CreateOrder
# ---------------------------------------------------------------------------


class TestCreateOrder:
    def test_happy_path_no_lines(self):
        client = _mock_client(post_response=sample_api_response(value={"id": 50}))
        handler = get_handler("create_order")
        assert handler is not None
        result = handler.execute(client, {"customer": 3, "orderDate": "2026-01-15"})
        assert result["id"] == 50
        assert result["action"] == "created"
        body = client.post.call_args[1]["data"]
        assert body["customer"] == {"id": 3}
        assert body["orderDate"] == "2026-01-15"

    def test_with_order_lines(self):
        # First post returns order, second returns order lines (batch endpoint)
        client = MagicMock()
        client.post.side_effect = [
            sample_api_response(value={"id": 50}),
            sample_api_response(values=[{"id": 101}]),
        ]
        handler = get_handler("create_order")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "customer": 1,
                "orderLines": [{"product": 7, "count": 2, "unitPriceExcludingVatCurrency": 100.0}],
            },
        )
        assert result["id"] == 50
        assert result["action"] == "created"
        assert client.post.call_count == 2

    def test_bulk_order_lines(self):
        client = MagicMock()
        client.post.side_effect = [
            sample_api_response(value={"id": 60}),
            sample_api_response(values=[{"id": 201}, {"id": 202}]),
        ]
        handler = get_handler("create_order")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "customer": 1,
                "orderLines": [
                    {"product": 7, "count": 1},
                    {"product": 8, "count": 3},
                ],
            },
        )
        assert result["action"] == "created"
        # Second call should be to /order/orderline/list for bulk
        second_call = client.post.call_args_list[1]
        assert "/order/orderline/list" in second_call[0][0]


# ---------------------------------------------------------------------------
# CreateInvoice
# ---------------------------------------------------------------------------


class TestCreateInvoice:
    def test_happy_path(self):
        client = MagicMock()
        # First POST = order, second POST = invoice
        client.post.side_effect = [
            sample_api_response(value={"id": 50}),
            sample_api_response(value={"id": 100}),
        ]
        handler = get_handler("create_invoice")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "customer": 3,
                "invoiceDate": "2026-03-01",
                "invoiceDueDate": "2026-03-31",
            },
        )
        assert result["id"] == 100
        assert result["orderId"] == 50
        assert result["action"] == "created"

    def test_with_lines(self):
        client = MagicMock()
        # POST order, POST orderline, POST invoice
        client.post.side_effect = [
            sample_api_response(value={"id": 50}),
            sample_api_response(value={"id": 101}),
            sample_api_response(value={"id": 200}),
        ]
        handler = get_handler("create_invoice")
        assert handler is not None
        result = handler.execute(
            client,
            {
                "customer": 1,
                "orderLines": [{"product": 7, "count": 1}],
                "invoiceDate": "2026-03-01",
            },
        )
        assert result["id"] == 200
        assert client.post.call_count == 3


# ---------------------------------------------------------------------------
# SendInvoice
# ---------------------------------------------------------------------------


class TestSendInvoice:
    def test_happy_path(self):
        client = _mock_client()
        handler = get_handler("send_invoice")
        assert handler is not None
        result = handler.execute(client, {"invoiceId": 100})
        assert result["id"] == 100
        assert result["action"] == "sent"
        client.post.assert_called_once()
        endpoint = client.post.call_args[0][0]
        assert "/:send" in endpoint


# ---------------------------------------------------------------------------
# RegisterPayment
# ---------------------------------------------------------------------------


class TestRegisterPayment:
    def test_with_invoice_id(self):
        client = _mock_client()
        handler = get_handler("register_payment")
        assert handler is not None
        result = handler.execute(
            client, {"invoiceId": 100, "amount": 5000, "paymentDate": "2026-03-15"}
        )
        assert result["id"] == 100
        assert result["action"] == "payment_registered"
        endpoint = client.put.call_args[0][0]
        assert "/:payment" in endpoint

    def test_search_by_invoice_number(self):
        inv = make_invoice(invoice_id=42, invoice_number=10001)
        client = _mock_client(get_response=sample_api_response(values=[inv]))
        handler = get_handler("register_payment")
        assert handler is not None
        result = handler.execute(client, {"invoiceNumber": 10001, "amount": 1000})
        assert result["id"] == 42

    def test_invoice_not_found(self):
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("register_payment")
        assert handler is not None
        result = handler.execute(client, {"invoiceNumber": 99999, "amount": 500})
        assert result.get("error") == "invoice_not_found"


# ---------------------------------------------------------------------------
# CreateCreditNote
# ---------------------------------------------------------------------------


class TestCreateCreditNote:
    def test_happy_path(self):
        inv = make_invoice(invoice_id=42)
        client = MagicMock()
        client.get.return_value = sample_api_response(values=[inv])
        client.put.return_value = sample_api_response(value={"id": 300})
        handler = get_handler("create_credit_note")
        assert handler is not None
        result = handler.execute(client, {"invoiceNumber": 10001})
        assert result["id"] == 300
        assert result["invoiceId"] == 42
        assert result["action"] == "credit_note_created"

    def test_invoice_not_found(self):
        client = _mock_client(get_response=sample_api_response(values=[]))
        handler = get_handler("create_credit_note")
        assert handler is not None
        result = handler.execute(client, {"invoiceNumber": 99999})
        assert result.get("error") == "invoice_not_found"
