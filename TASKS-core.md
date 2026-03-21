# Agent Plan: core-agent

**Owner**: core-agent (exclusively). Lead-agent creates tasks here; you fill out checklists and results.

## Active Tasks

### T11: Tripletex API client
**Status**: done
**Branch**: `core/T11-api-client`
**Target**: Robust HTTP client that handles auth, errors, rate limits, and field selection
**File**: `src/api_client.py`

- [x] Create `TripletexClient` class that takes `base_url` and `session_token`
- [x] Implement Basic Auth (username="0", password=session_token)
- [x] Implement `get(endpoint, params)` method with field selection support
- [x] Implement `post(endpoint, data)` method
- [x] Implement `put(endpoint, data)` method
- [x] Implement `delete(endpoint)` method
- [x] Parse error responses: extract `validationMessages`, `developerMessage`
- [x] Handle 429 rate limiting with exponential backoff (max 3 retries)
- [x] Do NOT retry on 4xx errors (they hurt efficiency score)
- [x] Log all API calls: method, endpoint, status code, duration
- [x] Track API call count for efficiency monitoring
- [x] Use `httpx` (async-capable) for HTTP requests
- [x] Keep under 200 lines
- [x] Self-review: lint + type check
- [x] Tests pass

**Key design decisions:**
- Use `httpx.Client` (sync) for simplicity. Async not needed with 5-min timeout.
- Field selection: pass `fields` param to minimize response size
- Always set `Content-Type: application/json`
- Return parsed JSON response, raise structured exceptions on error

**Result**: Implemented. 160 lines. 16 tests pass. Lint + mypy clean.

---

### T12: LLM integration
**Status**: done
**Branch**: `core/T12-llm-integration`
**Target**: LLM client that classifies tasks and extracts structured parameters
**File**: `src/llm.py`

- [x] Create `LLMClient` class
- [x] Support Claude API (primary) via `anthropic` library
- [ ] Support Gemini via Vertex AI (fallback, free on GCP) — deferred, Claude is primary
- [x] Implement `classify_and_extract(prompt, files)` method
- [x] Return structured output: `{"task_type": str, "params": dict}`
- [x] Build system prompt with all 30 task types and expected parameter schemas
- [x] Handle file attachments: decode base64, pass images/PDFs to LLM vision
- [x] Handle all 7 languages (LLM handles this naturally)
- [x] Add timeout (30 seconds max for LLM call)
- [x] Add error handling: retry once on transient failures
- [x] Keep under 200 lines
- [x] Self-review: lint + type check
- [x] Tests pass

**Result**: Implemented. 179 lines. 10 tests pass. Lint + mypy clean. Gemini fallback deferred — not needed unless Claude quota is an issue.

---

### T13: Task router
**Status**: done
**Branch**: `core/T13-task-router`
**Target**: Route classified task to the correct handler and execute it
**File**: `src/task_router.py`

- [x] Create `TaskRouter` class
- [x] Accept handler registry (from feature-agent's registry)
- [x] Accept LLM client and API client as dependencies
- [x] Implement `solve(request: SolveRequest) -> SolveResponse` method
- [x] Flow: parse request -> call LLM to classify -> lookup handler -> execute handler -> return response
- [x] Handle unknown task types gracefully (log warning, return completed)
- [x] Handle LLM classification failures (retry once with rephrased prompt)
- [x] Log: task_type, params extracted, handler used, API calls made, total duration
- [x] Keep under 100 lines
- [x] Self-review: lint + type check
- [x] Tests pass

**Result**: Implemented. 95 lines. 6 new tests pass (93 total). Lint clean. Server wiring already in place via `create_router()` factory.

---

### T60: Efficiency optimization
**Status**: done
**Branch**: `core/T60-efficiency`
**Target**: Minimize API call count per task, target optimal call sequence

- [x] Audit each handler's API call sequence
- [x] Remove unnecessary GET calls used for verification
- [x] Use batch endpoints (`/list`) where available — order lines always use `/order/orderline/list` (even for 1 line)
- [x] Ensure no redundant lookups (cache entity IDs within a task)
- [x] Document optimal call count per task type in constants (all 28 task types covered)
- [x] Self-review: lint + type check
- [x] Tests pass

**What changed**: Unified order line creation to always use batch endpoint (saves conditional branch, same 1 API call). Removed all standalone `_resolve_ref` functions in favor of `BaseHandler.ensure_ref`. All handlers now use `strip_none_values` to prevent sending None fields. Updated `OPTIMAL_CALL_COUNTS` with all 28 task types.

**Metrics**: Order with 1 line: 2 calls (was 2, now consistently batch). No verification GETs were found — handlers already minimal. Constants now cover all task types.

**Tests**: 226 pass, 0 fail.

---

### T61: Error elimination
**Status**: done
**Branch**: `core/T61-error-elimination`
**Target**: Zero 4xx errors on all submissions

- [x] Audit all POST/PUT payloads for required fields per endpoint
- [x] Add pre-validation in API client before sending requests (strip None values from POST/PUT bodies)
- [x] Validate date formats (yyyy-MM-dd) via `BaseHandler.validate_date()`
- [x] Validate ID references via `BaseHandler.ensure_ref()` (int -> {"id": N} safely)
- [x] Handle edge cases: empty strings, null values, missing optional fields (`strip_none_values`)
- [x] Self-review: lint + type check
- [x] Tests pass

**What changed**: Added 3 static methods to `BaseHandler`: `ensure_ref()`, `validate_date()`, `strip_none_values()`. All 10 handler files updated to use these helpers. API client now strips None values from POST/PUT bodies before sending. API client `post()`/`put()` signatures accept `list[dict]` for batch endpoints.

**Metrics**: Before: bare `_resolve_ref` per handler (no type safety on bad inputs, no logging). After: centralized `ensure_ref` with warning on bad types, `validate_date` with regex check, None stripping at both handler and API client level.

**Tests**: 226 pass, 0 fail. Lint clean. mypy clean.

---

### T70: Sandbox exploration scripts
**Status**: done
**Branch**: `core/T70-sandbox-exploration`
**Target**: Programmatically discover required/optional fields for every competition-relevant API endpoint. Output a field manifest that handlers can reference to build correct payloads on first try.
**File**: `src/sandbox_explorer.py`

- [x] Create `SandboxExplorer` class that takes a `TripletexClient`
- [x] For each key endpoint (`/employee`, `/customer`, `/product`, `/invoice`, `/order`, `/department`, `/project`, `/travelExpense`, `/ledger/voucher`, `/bank/reconciliation`, `/activity`, `/asset`, `/order/orderline`, `/ledger/account`):
  - [x] GET with `?fields=*` to discover all available response fields
  - [x] Attempt minimal POST to discover required fields from validation errors
  - [x] Record: endpoint, method, required fields, optional fields, field types, enum values
- [x] Output structured JSON manifest: `docs/field_manifest.json`
- [x] Include a markdown summary: `docs/field_manifest.md` (one table per endpoint)
- [x] Script should be runnable standalone: `python -m src.sandbox_explorer --base-url <url> --token <token>`
- [x] Handle errors gracefully — a 422 with validationMessages IS the data we want
- [x] Discover nested object requirements (e.g., order lines within orders, VAT types for products)
- [x] Discover reference requirements (e.g., which IDs must exist before creating an invoice)
- [x] Keep under 300 lines
- [x] Self-review: lint + type check

**Why this matters:**
- Eliminates guesswork when building handlers
- Prevents 4xx errors (the #1 efficiency score killer)
- Discovers fields the docs don't mention or that are context-dependent
- Handlers built from this manifest will be correct on first API call

**Result**: Implemented. 289 lines. 20 new tests (116 total pass). Lint clean. CLI entry point works via `python -m src.sandbox_explorer --base-url <url> --token <token>`. Explores 14 endpoints with GET field discovery and POST validation error extraction. Outputs JSON and markdown manifests.

---

---

## Day 2 Tasks (Saturday March 21)

### T100: Fix payment reversal scoring [CRITICAL]
**Status**: open
**Priority**: 1 (biggest single score improvement)
**Files**: `src/handlers/invoice.py` (RegisterPaymentHandler)

Current approach creates invoice WITHOUT payment for reversals → 2/8 score.
Competition may want to see a paid invoice with the payment then reversed.

- [ ] Check Tripletex API docs for payment reversal/cancellation endpoints
- [ ] Try approach A: create invoice + pay + reverse with negative paidAmount
- [ ] Try approach B: create invoice + pay, then use PUT /invoice/{id}/:createCreditNote
- [ ] Try approach C: current approach (leave unpaid) — already scoring 2/8
- [ ] Pick whichever scores highest, deploy
- [ ] Verify with at least 2 competition submissions

### T101: Verify product search-first fix
**Status**: open
**Priority**: 1
**Files**: `src/handlers/resolvers.py` (resolve_product)

- [ ] Confirm next invoice submission with pre-existing products scores >0
- [ ] If still failing, check if order line unitPriceExcludingVatCurrency overrides product price

### T102: Verify timesheet + salary fixes
**Status**: open
**Priority**: 1
**Files**: `src/handlers/timesheet.py`, `src/handlers/salary.py`

- [ ] Confirm next log_timesheet submission succeeds (projectChargeableHours removed)
- [ ] Confirm next run_payroll submission succeeds (employment check added)

---

## Escalations

_None_
