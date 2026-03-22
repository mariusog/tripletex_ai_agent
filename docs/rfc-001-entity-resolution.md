# RFC-001: Consolidate Entity Resolution and Separate Domain Finders

## Problem

Entity resolution (find-or-create entities by name/ID) is split across two files with unclear boundaries:

- **`src/handlers/entity_resolver.py`** (284 lines) — the "real" resolvers behind a `resolve()` entry point
- **`src/handlers/resolvers.py`** (215 lines) — backward-compat re-exports of the above, PLUS unrelated domain utilities (`ensure_bank_account`, `find_travel_expense`, `find_invoice_id`, `find_cost_category`, `get_travel_payment_type`)

This causes:
- **Inconsistent imports**: handlers import from both files — some use `entity_resolver.resolve`, others use `resolvers.resolve_customer`
- **Mixed concerns**: `resolvers.py` mixes generic entity find-or-create with travel/invoice-specific finders and bank account infrastructure
- **Backward-compat wrappers**: `resolvers.py` has `resolve_customer = _resolve_customer` re-exports that exist solely for legacy compatibility
- **Circular dependency**: `_resolve_employee` imports `HANDLER_REGISTRY["create_employee"]` at call time

## Proposed Interface

Consolidate into two clearly-scoped modules:

### `src/handlers/entity_resolver.py` — Entity find-or-create (single entry point)

```python
def resolve(
    api_client: TripletexClient,
    entity_type: str,   # "customer" | "supplier" | "product" | "employee" | "activity"
    value: str | int | dict,
    *,
    create_if_missing: bool = True,
    extra_create_fields: dict | None = None,
) -> dict[str, int]:
    """Find-or-create an entity. Returns {"id": N}."""
```

All private `_resolve_*` functions remain internal dispatch targets. No per-type public functions.

### `src/handlers/api_helpers.py` — Domain-specific finders and infrastructure

```python
def find_invoice_id(api_client, params) -> int | None
def find_travel_expense(api_client, params) -> int | None
def find_cost_category(api_client, description, cache=None) -> dict | None
def get_travel_payment_type(api_client) -> dict | None
def ensure_bank_account(api_client) -> None

COST_CATEGORY_MAP: dict[str, str]
```

### Caller usage (unchanged for common case):

```python
from src.handlers.entity_resolver import resolve
from src.handlers.api_helpers import find_invoice_id, ensure_bank_account

customer_ref = resolve(api_client, "customer", params["customer"])
```

## Dependency Strategy

- **In-process**: pure function calls through `TripletexClient`, no I/O beyond API calls
- **Circular import** (`_resolve_employee` -> `HANDLER_REGISTRY`): keep lazy import inside function body — pragmatic, already works, contained to one code path
- `api_helpers.py` has zero dependency on `entity_resolver.py` and vice versa

## Testing Strategy

- **New boundary tests to write**: test `resolve()` with `create_if_missing=False` (new capability); test each entity type through the unified `resolve()` entry point
- **Old tests to delete**: `test_resolvers.py` tests that exercise backward-compat wrappers (`resolve_customer`, `resolve_product`) become redundant once wrappers are removed
- **Test environment needs**: existing mock patterns for `TripletexClient` are sufficient

## Implementation Recommendations

- **What the module should own**: all entity find-or-create logic — search by name/number, create if missing, ID passthrough, name normalization
- **What it should hide**: per-entity-type search endpoints, creation payloads, fuzzy matching, employee creation indirection
- **What it should expose**: `resolve(api_client, entity_type, value, *, create_if_missing, extra_create_fields)` — one function
- **Migration path**:
  1. Create `src/handlers/api_helpers.py` with domain finders moved from `resolvers.py`
  2. Add `create_if_missing` param to existing `resolve()` in `entity_resolver.py`
  3. Update all handler imports from `resolvers.py` to `entity_resolver.py` or `api_helpers.py`
  4. Delete `resolvers.py`
  5. Each step keeps all tests passing
