# Tasks

**Owner**: lead-agent (exclusively). Other agents read this file but do not write to it.

Each agent has a separate plan file with detailed checklists:
- [TASKS-core.md](TASKS-core.md) -- core-agent tasks
- [TASKS-feature.md](TASKS-feature.md) -- feature-agent tasks
- [TASKS-qa.md](TASKS-qa.md) -- qa-agent tasks

## Format

Each task has: ID, status, agent, title, details, and optional dependencies.

**Statuses**: `open`, `in-progress`, `done`, `blocked`, `deferred`

---

## Architecture Overview

```
src/
  server.py          # FastAPI app with POST /solve endpoint (lead-agent)
  models.py          # Pydantic request/response models (lead-agent)
  api_client.py      # Tripletex REST API client (core-agent)
  llm.py             # LLM integration for prompt parsing (core-agent)
  task_router.py     # Classify prompt -> dispatch to handler (core-agent)
  constants.py       # All config values (lead-agent)
  __init__.py
  handlers/
    __init__.py      # Handler registry (feature-agent)
    base.py          # Base handler class (feature-agent)
    employee.py      # Employee CRUD handlers (feature-agent)
    customer.py      # Customer CRUD handlers (feature-agent)
    product.py       # Product CRUD handlers (feature-agent)
    department.py    # Department handlers (feature-agent)
    project.py       # Project handlers (feature-agent)
    invoice.py       # Invoice + payment handlers (feature-agent)
    order.py         # Order handlers (feature-agent)
    travel.py        # Travel expense handlers (feature-agent)
    ledger.py        # Ledger/voucher handlers (feature-agent)
    bank.py          # Bank reconciliation handlers (feature-agent)
tests/
  conftest.py        # Shared fixtures (qa-agent)
  test_models.py     # Request/response model tests (qa-agent)
  test_api_client.py # API client tests (qa-agent)
  test_llm.py        # LLM integration tests (qa-agent)
  test_task_router.py # Router tests (qa-agent)
  test_handlers/     # Handler tests (qa-agent)
```

## File Ownership

| Agent | Owned Files |
|-------|-------------|
| lead-agent | `src/server.py`, `src/models.py`, `src/constants.py`, `TASKS.md`, `TASKS-*.md`, `CLAUDE.md`, `pyproject.toml` |
| core-agent | `src/api_client.py`, `src/llm.py`, `src/task_router.py` |
| feature-agent | `src/handlers/*` (all handler files) |
| qa-agent | `tests/*`, `docs/benchmark_results.md` |

---

## Open Tasks

### PRIORITY 1: Foundation (must complete first)

| ID | Agent | Title | Details | Depends on |
|----|-------|-------|---------|------------|
| T10 | lead-agent | Server + models | FastAPI POST /solve endpoint, Pydantic models, Dockerfile, deployment config | - |
| T11 | core-agent | Tripletex API client | HTTP client with Basic Auth, retry on 429, field selection, error parsing | - |
| T12 | core-agent | LLM integration | Claude/Gemini integration for task classification and parameter extraction | - |
| T13 | core-agent | Task router | Classify prompt into task type, extract params, dispatch to handler | T11, T12 |
| T14 | feature-agent | Handler base + registry | Base handler class, registry pattern, handler interface | - |
| T15 | qa-agent | Test infrastructure | Fixtures for mock API responses, mock LLM, fake credentials | - |

### PRIORITY 2: Tier 1 Handlers (simple CRUD, x1 multiplier)

| ID | Agent | Title | Details | Depends on |
|----|-------|-------|---------|------------|
| T20 | feature-agent | Employee handlers | Create employee (with roles), update contact info | T14 |
| T21 | feature-agent | Customer handlers | Create customer, update customer | T14 |
| T22 | feature-agent | Product handlers | Create product with VAT type | T14 |
| T23 | feature-agent | Department handlers | Create department, assign manager | T14 |
| T24 | feature-agent | Project handlers | Create project, link to customer/department | T14 |

### PRIORITY 3: Tier 2 Handlers (multi-step, x2 multiplier)

| ID | Agent | Title | Details | Depends on |
|----|-------|-------|---------|------------|
| T30 | feature-agent | Order + invoice handlers | Create order with lines, create invoice from order | T14, T20, T21, T22 |
| T31 | feature-agent | Payment handlers | Register payment on invoice, credit notes | T30 |
| T32 | feature-agent | Travel expense handlers | Create travel expense with costs, deliver, approve | T14, T20 |
| T33 | feature-agent | Project linking handlers | Link project to customer, assign activities | T24 |

### PRIORITY 4: Tier 3 Handlers (complex, x3 multiplier, opens Saturday)

| ID | Agent | Title | Details | Depends on |
|----|-------|-------|---------|------------|
| T40 | feature-agent | Ledger/voucher handlers | Create voucher, reverse voucher, ledger corrections | T14 |
| T41 | feature-agent | Bank reconciliation handlers | Bank reconciliation workflow | T14 |
| T42 | feature-agent | Advanced workflows | Year-end closing, multi-step accounting tasks | T14, T40 |

### PRIORITY 5: Testing + Quality

| ID | Agent | Title | Details | Depends on |
|----|-------|-------|---------|------------|
| T50 | qa-agent | Unit tests for core modules | Tests for api_client, llm, task_router | T11, T12, T13 |
| T51 | qa-agent | Unit tests for Tier 1 handlers | Tests for employee, customer, product, department, project | T20-T24 |
| T52 | qa-agent | Unit tests for Tier 2 handlers | Tests for invoice, payment, travel, project linking | T30-T33 |
| T53 | qa-agent | Integration test harness | End-to-end test with sandbox credentials | T10, T13 |

### PRIORITY 6: Exploration + Hardening

| ID | Agent | Title | Details | Depends on |
|----|-------|-------|---------|------------|
| T60 | core-agent | Efficiency optimization | Audit API call counts, remove unnecessary GETs, use batch endpoints | T50, T51 |
| T61 | core-agent | Error elimination | Pre-validate all inputs, eliminate 4xx errors | T50, T51 |
| T70 | core-agent | Sandbox exploration scripts | Programmatically discover required/optional fields per API endpoint using sandbox. Output a field manifest (JSON) per endpoint. | T11 |
| T71 | qa-agent | Task-prompt test harness | Collect example prompts in all 7 languages for each task type. Build a test suite verifying classification accuracy across languages. | T12, T13 |
| T72 | feature-agent | Expand Tier 2/3 handler coverage | Build handlers for ALL 30 task types. Each Tier 2 handler = ~4 pts, each Tier 3 = ~6 pts. Prioritize by point value. | T14, T70 |

## In Progress

| ID | Agent | Title | Status | Notes |
|----|-------|-------|--------|-------|
| T60 | lead-agent | Efficiency optimization | in-progress | register_payment 9→5-6 calls done, create_project 4→2-3 pending |
| T72 | lead-agent | Task type coverage | in-progress | 6/30 task types seen in competition, need more submissions |
| T80 | lead-agent | Competition scoring fixes | in-progress | Fixing field mapping issues (address, dimensions) as discovered |

## New Tasks (discovered during competition)

| ID | Agent | Title | Details | Status |
|----|-------|-------|---------|--------|
| T81 | lead-agent | Reduce create_project calls | 4 calls → 2 (cache account owner, skip employee search) | open |
| T82 | lead-agent | Reduce create_invoice calls | 8 calls → 5 (bank acct cached, customer create-first done) | partially done |
| T83 | lead-agent | Few-shot classification examples | Add examples for confusing task pairs in LLM prompt | open |
| T84 | lead-agent | Verify all scoring fields | Compare our handler output fields vs what scoring checks | open |

## Done

| ID | Agent | Title | Result |
|----|-------|-------|--------|
| T10 | lead-agent | Server + models | FastAPI /solve + POST / endpoints, Pydantic models, Dockerfile, Cloud Run deploy |
| T11 | core-agent | Tripletex API client | HTTP client with auth, retry, caching layer (get_cached + global cache) |
| T12 | core-agent | LLM integration | Claude Opus 4.6 via Vertex AI, tool_use structured output, multilingual keywords |
| T13 | core-agent | Task router | Classify → dispatch with placeholder stripping, retry on failure |
| T14 | feature-agent | Handler base + registry | 30 handlers registered via @register_handler decorator |
| T15 | qa-agent | Test infrastructure | 254 tests, mock fixtures, prompt fixtures for all 30 task types |
| T20 | feature-agent | Employee handlers | Create (EXTENDED userType for admin), update. Pre-fetch dept. |
| T21 | feature-agent | Customer handlers | Create/update with postalAddress+physicalAddress, isSupplier flag |
| T22 | feature-agent | Product handlers | Create without price (avoids VAT conflict), number as string |
| T23 | feature-agent | Department handlers | Create department |
| T24 | feature-agent | Project handlers | Create project with customer + PM resolution, cached account owner |
| T30 | feature-agent | Order + invoice handlers | Full flow: order→lines→invoice→send. Auto-send when prompted. |
| T31 | feature-agent | Payment handlers | Register payment via CreateInvoiceHandler delegation (saves 2 calls) |
| T32 | feature-agent | Travel expense handlers | Create/deliver/approve/delete travel expenses with costs + per diem |
| T33 | feature-agent | Project linking handlers | Link project to customer, create activities |
| T40 | feature-agent | Ledger/voucher handlers | Create/delete vouchers, custom dimensions, split debit/credit format |
| T41 | feature-agent | Bank reconciliation | Account number resolution, type=MANUAL default, accountingPeriod |
| T42 | feature-agent | Advanced workflows | Year-end closing (auto-generate postings), balance sheet, ledger correction |
| T50 | qa-agent | Unit tests | 254 tests covering all 30 handlers |
| T53 | qa-agent | Integration harness | sim_all_tasks.py — 30/30 pass against sandbox |
| T61 | core-agent | Error elimination | 13 OpenAPI bugs fixed (wrong HTTP methods, readOnly fields, invalid names) |
| T70 | core-agent | API spec audit | OpenAPI spec downloaded, schemas extracted, all handlers validated |
| T75 | lead-agent | Competition run capture | capture_runs.py + summarize_runs.py + teammate service polling |
| T76 | lead-agent | Isolated deployment | deploy-magnus.sh — separate Cloud Run service from teammates |
