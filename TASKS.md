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

## Day 2 Game Plan (Saturday March 21)

Based on 80 competition runs. **16/30 task types seen, 14 never tested.**

### PRIORITY 1: Fix Broken Scoring [CRITICAL]

| ID | Agent | Task | Issue | Tier |
|----|-------|------|-------|------|
| T100 | core-agent | Fix payment reversal | 2/8 score — try paying then reversing with negative amount vs leaving unpaid | T2 x2 |
| T101 | core-agent | Verify product search-first fix | Was 0/8 when products pre-exist, now searches first | T2 x2 |
| T102 | core-agent | Verify timesheet + salary fixes | projectChargeableHours removed, employment check added | T2 x2 |

### PRIORITY 2: Reduce API Calls [EFFICIENCY]

| ID | Agent | Task | Current → Target | How |
|----|-------|------|------------------|-----|
| T110 | feature-agent | Optimize create_invoice | 7-10 → 4 calls | Use get_cached for bank acct + payment type |
| T111 | feature-agent | Optimize register_payment | 6-10 → 4 calls | Same as invoice optimization |
| T112 | feature-agent | Optimize create_project | 4-7 → 2 calls | Cache employee, skip redundant lookups |
| T113 | feature-agent | Optimize create_voucher | 4-5 → 2 calls | Cache account lookups with get_cached |

### PRIORITY 3: Test Untested Task Types [14 NEVER SEEN]

| ID | Agent | Task Types | Tier | Action |
|----|-------|------------|------|--------|
| T120 | qa-agent | balance_sheet_report, bank_reconciliation, ledger_correction, year_end_closing, reverse_voucher, delete_voucher | T3 x3 | Write sandbox integration tests |
| T121 | qa-agent | create_order, create_asset, update_asset, approve_travel_expense, deliver_travel_expense | T2 x2 | Write sandbox integration tests |
| T122 | qa-agent | assign_role, enable_module, update_customer, update_employee | T1 x1 | Write sandbox integration tests |

### PRIORITY 4: Cross-Service Optimization

| ID | Agent | Task | Action |
|----|-------|------|--------|
| T130 | lead-agent | Compare handlers across services | Use runs/handler_snapshots/, cherry-pick best per task |
| T131 | lead-agent | Merge Magnus branch improvements | Port remaining improvements (if any) |

## Completed (Day 1)

| What | Result |
|------|--------|
| All 30+ handlers implemented | ✅ |
| Tool use for LLM (structured output) | ✅ |
| get_cached for API response caching | ✅ |
| PUT /order/:invoice (single call) | ✅ |
| Create-first pattern for entities | ✅ |
| Bank account cache per-sandbox | ✅ |
| Credit note PUT (not POST) | ✅ |
| Placeholder stripping | ✅ |
| Run capture + analysis pipeline | ✅ |
| COMPETITION_RUN logging | ✅ |
