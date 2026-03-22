# RFC-002: Extract Invoice Service and Shared Order Line Builder

## Problem

`src/handlers/invoice.py` is 384 lines (exceeds 300-line limit). The core issue:

- `CreateInvoiceHandler.execute` is ~145 lines (exceeds 30-line limit) orchestrating 6 steps: ensure bank account, resolve customer, maybe create project, create order, build+post order lines, create invoice, maybe register payment
- `RegisterPaymentHandler` and `CreateCreditNoteHandler` both instantiate `CreateInvoiceHandler()` directly as a sub-step, creating tight coupling — you can't test payment or credit note logic without running the full invoice creation flow
- Order line building (~25 lines) is duplicated identically between `invoice.py:97-126` and `order.py:48-77`

## Proposed Interface

### `src/services/order_line_builder.py` — Shared order line building

```python
@dataclass
class OrderLineInput:
    description: str
    count: float
    unit_price_excl_vat: float
    product_id: int | None = None

def build_and_post_order_lines(
    api_client: TripletexClient,
    order_id: int,
    lines: list[dict[str, Any]],
) -> list[int]:
    """Resolve products, normalize price aliases, POST order lines. Returns line IDs."""
```

Single source of truth for: product resolution, price field alias handling (unitPriceExcludingVatCurrency/amount/price), and order line payload construction.

### `src/services/invoice_service.py` — Invoice workflow orchestration

```python
@dataclass
class InvoiceResult:
    order_id: int
    invoice_id: int
    payment_id: int | None = None

def create_full_invoice(
    api_client: TripletexClient,
    customer: str | int | dict,
    order_lines: list[dict[str, Any]],
    *,
    invoice_date: str | None = None,
    project: str | int | dict | None = None,
    register_payment: bool = False,
    payment_date: str | None = None,
    send_invoice: bool = False,
) -> InvoiceResult:
    """Full flow: resolve entities -> order -> lines -> invoice -> optional payment."""

def create_invoice_from_order(
    api_client: TripletexClient,
    order_id: int,
    *,
    invoice_date: str | None = None,
) -> int:
    """Create invoice from existing order. Returns invoice_id. Used by secondary callers."""
```

### Slimmed handlers

```python
# invoice.py (~80 lines) — thin param parsers
class CreateInvoiceHandler:
    def execute(self, api_client, params):
        result = create_full_invoice(api_client, customer=params["customer"], ...)
        return {"id": result.invoice_id, "orderId": result.order_id}

class RegisterPaymentHandler:
    def execute(self, api_client, params):
        # No longer instantiates CreateInvoiceHandler
        if not invoice_id:
            result = create_full_invoice(api_client, ..., register_payment=True)
        ...

# order.py (~40 lines)
class CreateOrderHandler:
    def execute(self, api_client, params):
        # Uses shared build_and_post_order_lines instead of duplicated code
        ...
```

## Dependency Strategy

- **In-process**: stateless functions receiving `api_client` as parameter
- **Dependency direction**: handlers -> services -> entity_resolver + api_client
- **No handler imports another handler**: the handler-to-handler coupling is eliminated entirely
- `order_line_builder.py` depends only on `entity_resolver.resolve` and `TripletexClient`
- `invoice_service.py` depends on `order_line_builder`, `entity_resolver`, and `api_helpers`

```
handlers/invoice.py  -->  services/invoice_service.py  -->  services/order_line_builder.py
handlers/order.py   -->  services/order_line_builder.py     handlers/entity_resolver.py
                                                             handlers/api_helpers.py
```

## Testing Strategy

- **New boundary tests to write**: test `create_full_invoice()` and `create_invoice_from_order()` with mocked API client; test `build_and_post_order_lines()` with various price alias formats
- **Old tests to delete**: handler-level tests that currently test invoice creation through `RegisterPaymentHandler` or `CreateCreditNoteHandler` can be simplified to test only the handler's param-parsing, not the full flow
- **Test environment needs**: existing mock patterns for `TripletexClient` are sufficient

## Implementation Recommendations

- **What the service should own**: the multi-step order-to-invoice-to-payment API workflow, bank account setup, entity resolution dispatch
- **What it should hide**: API endpoint paths, order line payload format, payment type lookup, price field alias normalization
- **What it should expose**: `create_full_invoice()` for the common case, `create_invoice_from_order()` for secondary callers
- **Migration path**:
  1. Create `src/services/order_line_builder.py` extracting shared line-building logic
  2. Create `src/services/invoice_service.py` extracting orchestration from `CreateInvoiceHandler.execute`
  3. Update `CreateOrderHandler` to use `build_and_post_order_lines()`
  4. Update `RegisterPaymentHandler` and `CreateCreditNoteHandler` to call service functions
  5. Each step keeps all tests passing

Note: This RFC also resolves the order line duplication issue (Candidate 3 from the architecture review).
