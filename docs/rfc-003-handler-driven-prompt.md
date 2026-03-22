# RFC-003: Handler-Driven LLM Classification Prompt

## Problem

Adding or modifying a handler requires synchronized edits across three files:

1. **`src/constants.py`** — add to `TIER_1_TASKS`, `TIER_2_TASKS`, or `TIER_3_TASKS`
2. **`src/llm.py`** — add parameter schema and classification rules to 120-line `SYSTEM_PROMPT`
3. **The handler file** — implement the actual logic

Nothing enforces consistency. The prompt hard-codes parameter schemas for ~30 task types that can silently drift from what handlers actually accept. `required_params` on the handler is a minimal list that doesn't match the richer schema in the prompt.

## Proposed Interface

### Extended `BaseHandler` (in `src/handlers/base.py`)

```python
@dataclass(frozen=True)
class ParamSpec:
    type: str              # "string" | "number" | "boolean" | "date" | "object" | "list"
    required: bool = True
    description: str = ""  # used verbatim in the LLM prompt

class BaseHandler(ABC):
    # Existing
    @abstractmethod
    def get_task_type(self) -> str: ...
    @abstractmethod
    def execute(self, api_client, params) -> dict: ...

    # New — handler declares its own schema
    tier: int = 1                                    # 1, 2, or 3
    description: str = ""                            # one-line purpose for LLM
    param_schema: dict[str, ParamSpec] = {}           # param name -> spec
    disambiguation: str | None = None                # classification edge-case notes

    # Derived — no longer manually maintained
    @property
    def required_params(self) -> list[str]:
        return [k for k, v in self.param_schema.items() if v.required]
```

### Prompt generation (in `src/llm.py`)

```python
def build_system_prompt(handlers: dict[str, BaseHandler]) -> str:
    """Assemble classification prompt from handler metadata.
    Called once at startup. Returns the full system prompt string."""
```

### Handler usage example

```python
@register_handler
class CreateEmployeeHandler(BaseHandler):
    tier = 1
    description = "Create a new employee in Tripletex"
    param_schema = {
        "firstName": ParamSpec("string", required=True, description="Employee first name"),
        "lastName": ParamSpec("string", required=True, description="Employee last name"),
        "email": ParamSpec("string", required=False, description="Email address"),
        "userType": ParamSpec("string", required=False, description="STANDARD or ADMINISTRATOR"),
    }

    def get_task_type(self) -> str:
        return "create_employee"

    def execute(self, api_client, params):
        ...
```

## Dependency Strategy

- **In-process**: pure data declarations + string assembly, no new dependencies
- **Dependency direction**: `llm.py` reads handler metadata via `HANDLER_REGISTRY` (already imported). Handlers depend only on `base.py` (already the case). No new dependency edges.
- **No auto-discovery**: the explicit import list in `handlers/__init__.py` remains the registry. Adding a handler = create the file + add one import line (2 files, down from 3).
- **Tier lists derived**: `TIER_1_TASKS` etc. in `constants.py` become computed from `HANDLER_REGISTRY` or are deleted entirely. The handler's `tier` attribute is the source of truth.

```
handlers/*.py  --> base.py (ParamSpec, BaseHandler)
llm.py  --> HANDLER_REGISTRY (reads .tier, .description, .param_schema, .disambiguation)
constants.py  --> HANDLER_REGISTRY (derives tier lists) or deleted for task types
```

## Testing Strategy

- **New boundary tests to write**: test that `build_system_prompt()` produces valid prompt containing all registered task types and their params; test that every handler's `param_schema` keys are a superset of params actually used in `execute()`
- **Old tests to delete**: any tests asserting on the hard-coded `SYSTEM_PROMPT` string; tests for `TIER_*_TASKS` constants
- **Startup validation**: `build_system_prompt()` should validate at assembly time — no duplicate task types, every handler has a description, tier is in {1,2,3}

## Implementation Recommendations

- **What the module should own**: each handler owns its schema declaration (params, tier, description, disambiguation). `build_system_prompt()` owns prompt formatting.
- **What it should hide**: prompt template structure, parameter block formatting, tier grouping — callers never see how the prompt is assembled
- **What it should expose**: the assembled prompt string (for `LLMClient` to use) and optionally a `--dump-prompt` debug mode
- **Migration path**:
  1. Add `ParamSpec` dataclass and new attributes to `BaseHandler` with defaults (backward-compatible)
  2. Add `build_system_prompt()` to `llm.py` alongside existing `SYSTEM_PROMPT`
  3. Migrate handlers one at a time — each gets `tier`, `description`, `param_schema`
  4. Add a test asserting `build_system_prompt()` output matches existing `SYSTEM_PROMPT` semantically
  5. Once all handlers migrated, delete hard-coded `SYSTEM_PROMPT` and tier lists from `constants.py`
  6. Each step keeps all tests passing
