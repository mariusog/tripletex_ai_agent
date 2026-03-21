# RFC-004: Consolidate Delete Handlers into Parameterized Config

## Problem

`src/handlers/delete.py` (218 lines) contains 8 handler classes that all follow the identical pattern:

```python
@register_handler
class Delete<Entity>Handler(BaseHandler):
    def get_task_type(self): return "delete_<entity>"
    @property
    def required_params(self): return ["name"]
    def execute(self, api_client, params):
        eid = _find_entity(api_client, "/<endpoint>", params)
        if not eid: return {"error": "not_found"}
        return _do_delete(api_client, "/<endpoint>", eid, "<entity>")
```

The per-handler classes are shallow modules where the interface (3 abstract methods) is nearly as complex as the implementation (1-3 lines each). Only 3 of 8 have any meaningful variation (product searches by number, voucher searches by date range, travel_expense searches by title).

## Proposed Interface

### Config-driven registration

```python
@dataclass
class DeleteEntityConfig:
    entity_name: str                              # e.g. "customer"
    endpoint: str                                 # e.g. "/customer"
    search_field: str = "name"                    # field used for search query
    required_params: list[str] = field(default_factory=lambda: ["name"])
    custom_find: Callable[[TripletexClient, dict], int | None] | None = None

DELETE_CONFIGS = [
    DeleteEntityConfig("customer",       "/customer"),
    DeleteEntityConfig("department",     "/department"),
    DeleteEntityConfig("project",        "/project"),
    DeleteEntityConfig("supplier",       "/supplier"),
    DeleteEntityConfig("order",          "/order",          required_params=["id"]),
    DeleteEntityConfig("product",        "/product",        custom_find=_find_product),
    DeleteEntityConfig("travel_expense", "/travelExpense",  custom_find=_find_travel_expense),
    DeleteEntityConfig("voucher",        "/ledger/voucher", custom_find=_find_voucher),
]

def register_delete_handlers(configs: list[DeleteEntityConfig]) -> None:
    """Create and register a DeleteHandler instance for each config."""
```

### Internal handler class

```python
class DeleteHandler(BaseHandler):
    """Generic delete handler, parameterized by DeleteEntityConfig."""

    def __init__(self, config: DeleteEntityConfig) -> None:
        self._config = config

    def get_task_type(self) -> str:
        return f"delete_{self._config.entity_name}"

    @property
    def required_params(self) -> list[str]:
        return self._config.required_params

    def execute(self, api_client, params) -> dict:
        if self._config.custom_find:
            eid = self._config.custom_find(api_client, params)
        else:
            eid = _find_entity(api_client, self._config.endpoint, params, self._config.search_field)
        if not eid:
            return {"error": "not_found"}
        return _do_delete(api_client, self._config.endpoint, eid, self._config.entity_name)
```

### Custom find functions (for the 3 entities with variation)

```python
def _find_product(api_client, params) -> int | None:
    """Search by number first, then by name."""
    ...

def _find_voucher(api_client, params) -> int | None:
    """Search by date range and voucher number."""
    ...

def _find_travel_expense(api_client, params) -> int | None:
    """Search by id, title, or employee."""
    ...
```

## Dependency Strategy

- **In-process**: no new dependencies, uses existing `BaseHandler`, `_find_entity`, `_do_delete`
- **Router unchanged**: `DeleteHandler` satisfies the same protocol (get_task_type, required_params, validate_params, execute). The router sees no difference.
- **Registration**: `register_delete_handlers()` calls the existing `HANDLER_REGISTRY` mechanism

## Testing Strategy

- **New boundary tests to write**: parameterized test over `DELETE_CONFIGS` — one test function replaces 8 test classes for the common case. Separate test functions for the 3 custom-find entities.
- **Old tests to delete**: 8 near-identical test classes in `test_delete_handlers.py` collapse into ~2-3 test functions
- **Test environment needs**: existing mock patterns for `TripletexClient` are sufficient

## Implementation Recommendations

- **What the module should own**: the find-then-delete pattern for all entity types
- **What it should hide**: the per-entity endpoint path, search field, and custom search logic
- **What it should expose**: the config list (for tests to parameterize over) and the registered handlers (via HANDLER_REGISTRY)
- **Migration path**:
  1. Add `DeleteEntityConfig` dataclass and `DeleteHandler` class
  2. Add `register_delete_handlers()` with the config list
  3. Verify all 8 task types are registered and tests pass
  4. Delete the 8 individual handler classes
  5. Collapse tests into parameterized form
- **Estimated size**: ~80 lines (down from 218)
- **Escape hatch**: if a future delete operation needs truly custom logic, it can still be a manual `BaseHandler` subclass
