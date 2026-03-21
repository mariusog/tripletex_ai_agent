# Agent Plan: qa-agent

**Owner**: qa-agent (exclusively). Lead-agent creates tasks here; you fill out checklists and results.

## Active Tasks

### T15: Test infrastructure
**Status**: done
**Branch**: `qa/T15-test-infra`
**Target**: Reusable fixtures for all test modules

- [x] Update `tests/conftest.py` with competition-specific fixtures:
  - `fake_credentials` fixture: returns test base_url and session_token
  - `mock_api_client` fixture: returns a mocked TripletexClient
  - `mock_llm_client` fixture: returns a mocked LLMClient
  - `sample_solve_request` fixture: returns a valid SolveRequest
  - `sample_api_response` factory: builds Tripletex-style API responses
  - `sample_error_response` factory: builds error responses with validationMessages
  - `sample_solve_request_with_file` fixture: returns SolveRequest with PDF attachment
- [x] Create `tests/test_handlers/` directory with `__init__.py`
- [x] Create `tests/test_handlers/conftest.py` with handler-specific fixtures
  - `mock_handler_client` fixture with spec=TripletexClient
  - Entity factories: make_employee, make_customer, make_product, make_department, make_project, make_invoice, make_order
- [x] Create `tests/test_models.py` with 16 tests covering all models
  - SolveRequest: deserialization, files, roundtrip, missing fields, multiple attachments
  - SolveResponse: default status, serialization, custom status
  - TaskClassification: full, defaults, roundtrip
  - FileAttachment: valid, missing field
  - ApiError: minimal, full
- [x] Verify pytest runs clean: 16 model tests pass
- [x] Self-review: lint + format pass (ruff check + ruff format)
- [x] Added S105/S106 to per-file-ignores for tests in pyproject.toml
- [x] All files under 200 lines (conftest: 174, test_models: 197, handlers/conftest: 157)

**Result**: Test infrastructure complete. 16 new model tests pass. Fixtures provide `fake_credentials`, `mock_api_client`, `mock_llm_client`, `sample_solve_request`, `sample_solve_request_with_file`, `sample_api_response()`, `sample_error_response()`. Handler conftest provides `mock_handler_client` and 7 entity factory functions.

---

### T50: Unit tests for core modules
**Status**: done
**Branch**: `qa/T50-core-tests`
**Target**: 100% coverage of public methods in api_client, llm, task_router
**Files**: `tests/test_api_client.py`, `tests/test_llm.py`, `tests/test_task_router.py`

- [x] `test_api_client.py`:
  - test_get_sets_basic_auth (covered by test_get_returns_json + init auth)
  - test_get_passes_field_selection (test_get_with_fields)
  - test_post_sends_json_body (test_post_sends_json_body)
  - test_put_sends_json_body (test_put_sends_json_body)
  - test_delete_calls_endpoint (test_delete_204_returns_none)
  - test_handles_429_with_retry (test_retries_on_429_then_succeeds + test_exhausts_retries + test_exponential_backoff)
  - test_does_not_retry_on_4xx (test_404_raises_without_retry)
  - test_parses_error_response (test_400_raises_api_error + test_non_json_error_body)
  - test_tracks_call_count (test_tracks_multiple_calls + test_retries_do_not_increase_count)
  - All 18 tests existed from core-agent, verified passing
- [x] `test_llm.py`:
  - test_classify_returns_task_type_and_params (test_basic_classification)
  - test_handles_norwegian_prompt (NEW: added)
  - test_handles_file_attachments (test_image/pdf/text_attachment)
  - test_timeout_raises_error (NEW: added)
  - test_retries_on_transient_failure (test_retries_on_500 + NEW: test_retries_on_connection_error)
  - 13 tests total (10 existed, 3 added)
- [x] `test_task_router.py` (NEW file):
  - test_routes_to_correct_handler
  - test_unknown_task_type_returns_completed
  - test_handles_llm_failure_gracefully
  - test_logs_task_execution
  - test_llm_retry_on_first_failure (bonus)
  - test_handler_exception_still_returns_completed (bonus)
  - 7 tests total
- [x] Each file under 200 lines (api_client: 188, llm: 194, task_router: 166)
- [x] Self-review: lint + format pass (ruff check + ruff format)
- [x] All tests pass (93 total across full suite)

**Result**: T50 complete. Added 3 new tests to test_llm.py (Norwegian prompt, timeout, connection retry). Created test_task_router.py with 7 async tests covering routing, unknown tasks, LLM failure, logging, retry, and handler exceptions. All 93 tests pass. All files under 200 lines. Lint clean.

---

### T51: Unit tests for Tier 1 handlers
**Status**: open
**Branch**: `qa/T51-tier1-tests`
**Target**: 100% coverage of Tier 1 handler public methods
**File**: `tests/test_handlers/`

- [ ] `test_employee.py`:
  - test_create_employee_posts_correct_fields
  - test_create_employee_with_role
  - test_update_employee_searches_then_updates
  - test_create_employee_handles_department
- [ ] `test_customer.py`:
  - test_create_customer_posts_correct_fields
  - test_update_customer_searches_then_updates
- [ ] `test_product.py`:
  - test_create_product_posts_correct_fields
  - test_create_product_with_vat_type
- [ ] `test_department.py`:
  - test_create_department_posts_correct_fields
- [ ] `test_project.py`:
  - test_create_project_posts_correct_fields
  - test_create_project_with_customer_link
- [ ] Self-review: lint + type check
- [ ] All tests pass

**Result**: _pending_

---

### T52: Unit tests for Tier 2 handlers
**Status**: open
**Branch**: `qa/T52-tier2-tests`
**Target**: 100% coverage of Tier 2 handler public methods

- [ ] `test_invoice.py`:
  - test_create_invoice_creates_order_then_invoice
  - test_create_invoice_with_order_lines
  - test_register_payment_finds_invoice_then_pays
  - test_create_credit_note
- [ ] `test_travel.py`:
  - test_create_travel_expense
  - test_deliver_travel_expense
- [ ] Self-review: lint + type check
- [ ] All tests pass

**Result**: _pending_

---

### T53: Integration test harness
**Status**: open
**Branch**: `qa/T53-integration-tests`
**Target**: End-to-end test using sandbox credentials

- [ ] Create `tests/test_integration.py` (marked as `slow`)
- [ ] Test full flow: construct SolveRequest -> call router -> verify result
- [ ] Use real sandbox credentials (from env vars)
- [ ] Test at least one Tier 1 task end-to-end
- [ ] Test at least one Tier 2 task end-to-end
- [ ] Mark all integration tests with `@pytest.mark.slow`
- [ ] Self-review: lint + type check
- [ ] All tests pass

**Result**: _pending_

---

### T71: Task-prompt test harness
**Status**: done
**Branch**: `qa/T71-prompt-harness`
**Target**: Verify the LLM classifier correctly identifies all 30 task types across all 7 languages. Catch classification failures before they become scoring misses.
**Files**: `tests/test_prompt_harness.py`, `tests/prompt_harness_utils.py`, `tests/fixtures/prompts/`

- [x] Create `tests/fixtures/prompts/` directory with one JSON file per task type (28 files created)
- [x] Each JSON file contains example prompts in all 7 languages (no, en, es, pt, nn, de, fr) plus expected_params
- [x] Cover all Tier 1 (9), Tier 2 (13), and Tier 3 (6) task types = 28 total
- [x] Create `tests/test_prompt_harness.py`:
  - [x] `test_classification_accuracy_per_language` -- parametrized over 7 languages
  - [x] `test_classification_accuracy_per_task_type` -- parametrized over 28 task types
  - [x] `test_parameter_extraction_accuracy` -- parametrized over 28 task types, verifies param keys/values
  - [x] `test_all_task_types_have_fixtures` -- structural: every ALL_TASK_TYPES entry has a fixture
  - [x] `test_all_fixtures_have_all_languages` -- structural: every fixture has all 7 languages
  - [x] `test_accuracy_report_generation` -- verifies markdown matrix output
- [x] Create `tests/prompt_harness_utils.py` with `load_all_fixtures()`, `load_fixture()`, `generate_accuracy_matrix()`
- [x] Report accuracy matrix: generates task_type x language markdown table
- [x] Real LLM tests marked `@pytest.mark.slow` (test_real_llm_classification_per_language, test_real_llm_full_accuracy_report)
- [x] Target: >= 95% classification accuracy assertion in slow test
- [x] Keep each file under 200 lines (test: 190, utils: 79)
- [x] Self-review: lint + format pass (ruff check + ruff format)
- [x] All 66 non-slow tests pass

**Why this matters:**
- 7 languages x 28 tasks = 196 classification paths, each is a potential failure
- One misclassification = 0 points for that submission
- This harness catches regressions when we update the classification prompt
- The prompt fixtures double as training data for few-shot examples

**Result**: T71 complete. Created 28 prompt fixture JSON files covering all task types in 7 languages. Test file has 66 fast tests (mocked LLM) + 2 slow tests (real LLM). Utility module provides fixture loading and accuracy matrix generation. All tests pass. All files under 200 lines. Lint clean.

---

---

## Day 2 Tasks (Saturday March 21)

### T120: Integration tests for Tier 3 handlers [x3 multiplier]
**Status**: open
**Priority**: 3
**Files**: `tests/test_all_handlers_sandbox.py`

These 6 task types have NEVER been tested in competition. Each is worth x3 points.

- [ ] `balance_sheet_report` — GET /balanceSheet with date range
- [ ] `bank_reconciliation` — POST /bank/reconciliation with type + accountingPeriod
- [ ] `ledger_correction` — POST /ledger/voucher with correction postings
- [ ] `year_end_closing` — POST /ledger/voucher with closing entries from balance sheet
- [ ] `reverse_voucher` — PUT /ledger/voucher/{id}/:reverse
- [ ] `delete_voucher` — GET /ledger/voucher + DELETE

For each:
- [ ] Write sandbox integration test in test_all_handlers_sandbox.py
- [ ] Run against sandbox to verify handler works end-to-end
- [ ] Document any API quirks found

### T121: Integration tests for Tier 2 handlers [x2 multiplier]
**Status**: open
**Priority**: 3
**Files**: `tests/test_all_handlers_sandbox.py`

5 task types never tested in competition:

- [ ] `create_order` — POST /order + /order/orderline/list
- [ ] `create_asset` — POST /asset
- [ ] `update_asset` — GET /asset + PUT /asset/{id}
- [ ] `approve_travel_expense` — PUT /travelExpense/{id}/:approve
- [ ] `deliver_travel_expense` — PUT /travelExpense/{id}/:deliver

### T122: Integration tests for Tier 1 handlers [x1 multiplier]
**Status**: open
**Priority**: 3
**Files**: `tests/test_all_handlers_sandbox.py`

4 task types never tested in competition:

- [ ] `assign_role` — GET /employee + PUT /employee/{id} with userType
- [ ] `enable_module` — GET /modules + PUT /modules
- [ ] `update_customer` — GET /customer + PUT /customer/{id}
- [ ] `update_employee` — GET /employee + PUT /employee/{id}

---

## Escalations

_None_
