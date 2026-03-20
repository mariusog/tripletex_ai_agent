# Handover Guide — Tripletex AI Agent

## Current State

**Branch:** `Marius-attempt`
**Deployed:** `https://tripletex-agent-2-1084086839157.europe-west1.run.app`
**GCP Project:** `ai-nm26osl-1792` | **Region:** `europe-west1`
**LLM:** Claude Opus 4.6 via Vertex AI (`claude-opus-4-6`, region `us-east5`)

The agent is live and scoring on the competition leaderboard. Best results so far: 7/7 and 8/8 on some tasks, typically 5-7/8 on complex ones.

**MCP docs server configured:** `nmiai` — use `ListMcpResourcesTool` / `ReadMcpResourceTool` to query competition docs.

## Critical Scoring Insight

**ALL API calls count for efficiency** (GET, POST, PUT, DELETE). Minimize total calls.
- Don't verify after creation unless needed — you already have the ID from the response
- Cache lookups (e.g., bank account, payment types) across the handler
- Use batch endpoints (`/list`) where possible
- Every 4xx error also reduces the efficiency bonus

## Architecture

```
POST /solve request
  |
  v
LLM (Claude Opus 4.6 via Vertex AI)
  - Classifies task type (1 of 28 registered handlers)
  - Extracts structured params (names, amounts, dates, products)
  |
  v
TaskRouter -> Handler
  - Each handler makes deterministic Tripletex API calls
  - Auto-creates prerequisite entities (customer, employee, product, supplier)
  - Returns {"status": "completed"} regardless of outcome
```

### Key Files

| File | What it does |
|------|-------------|
| `src/server.py` | FastAPI `/solve` endpoint |
| `src/llm.py` | LLM classification + parameter extraction (system prompt is here) |
| `src/task_router.py` | Dispatches classified tasks to handlers |
| `src/api_client.py` | Tripletex HTTP client with auth, retry, error parsing |
| `src/handlers/invoice.py` | Most complex — full order->invoice->payment flow (459 lines) |
| `src/handlers/travel.py` | Travel expenses with cost lines (287 lines) |
| `src/handlers/ledger.py` | Vouchers with supplier + account resolution (195 lines) |
| `src/handlers/employee.py` | Employee creation with employment records |
| `src/constants.py` | All config: model IDs, timeouts, task type lists |

### Shared Resolvers (important!)

These functions search-or-create entities by name. All do **exact name matching** (Tripletex API search is fuzzy):

| Function | Location | Creates |
|----------|----------|---------|
| `_resolve_customer()` | `invoice.py` | Customer with org number |
| `_resolve_product()` | `invoice.py` | Product with name, number, price |
| `_resolve_employee()` | `travel.py` | Employee with employment record |
| `_resolve_supplier()` | `ledger.py` | Supplier with org number |
| `_resolve_account()` | `ledger.py` | Looks up ledger account by number (returns ID + VAT type) |

## How to Deploy

```bash
gcloud run deploy tripletex-agent-2 \
  --project ai-nm26osl-1792 \
  --region europe-west1 \
  --source /workspaces/tripletex_ai_agent \
  --allow-unauthenticated \
  --port 8080 \
  --timeout 300 \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 10 \
  --concurrency 1 \
  --set-env-vars "ANTHROPIC_VERTEX_PROJECT_ID=ai-nm26osl-1792,CLOUD_ML_REGION=us-east5"
```

## How to Test

### Unit tests (fast, no sandbox needed)
```bash
python -m pytest tests/ -q --tb=short -m "not slow" 2>&1 | tail -20
```

### Integration tests against sandbox (comprehensive)
```bash
export SANDBOX_URL="https://kkpqfuj-amager.tripletex.dev/v2"
export SANDBOX_TOKEN="eyJ0b2tlbklkIjoyMTQ3NjI5NjQ5LCJ0b2tlbiI6IjYzZWU1MTFlLTg2ZDAtNDk4Mi04NDY1LTFmZDIwNjBlNGE1ZSJ9"
python -m pytest tests/test_all_handlers_sandbox.py -v --tb=short -m slow
```

### Full e2e with LLM (tests classification + execution)
```bash
# Same env vars as above, then:
python3 /tmp/test_all_tasks.py  # or write your own prompts
```

### Check competition logs
```bash
gcloud run services logs read tripletex-agent-2 \
  --project ai-nm26osl-1792 --region europe-west1 --limit 50
```

## Hard-Won Lessons (Gotchas)

### Tripletex API Quirks

1. **Fuzzy search** — All name searches (`/customer?name=X`, `/employee?firstName=X`) return fuzzy matches or ALL results. Always verify exact name match in code.

2. **Bank account required** — Invoices cannot be created until ledger account 1920 has a `bankAccountNumber`. We auto-set `12345678903` on first invoice. Cached per session.

3. **Employee creation** — Requires `userType`. `STANDARD` needs `email`, `NO_ACCESS` does not. When auto-creating employees (for PM, travel, etc.), use `NO_ACCESS` if no email provided.

4. **Employment records** — Employees need an employment record with `startDate` and `employmentDetails` (type, percentage). Without this, competition checks fail.

5. **`dateOfBirth` required** — On both create and update. Default to `1990-01-01` if not in prompt.

6. **Invoice payment** — Uses `PUT /invoice/{id}/:payment` with **query params** (`paymentDate`, `paymentTypeId`, `paidAmount`), NOT POST with JSON body.

7. **Voucher postings** — Need `row` field (1-indexed), `amountGrossCurrency` (same as `amountGross`), and `sendToLedger=true` query param. Account-locked VAT types must be included.

8. **Supplier on voucher postings** — Supplier invoice vouchers need `supplier` ref on every posting, not just the AP line.

9. **Project manager access** — Newly created employees don't have PM access. Always use the first employee (account owner) as `projectManager` on projects.

10. **`deliveryDate` required** — Orders need both `orderDate` and `deliveryDate`.

### LLM Classification Issues

1. **Payment reversals** — LLM sometimes classifies as `reverse_voucher` instead of `register_payment`. Fixed in system prompt, with fallback in handler.

2. **Array responses** — LLM occasionally returns `[{...}]` instead of `{...}`. Parser handles this.

3. **Multi-step tasks** — Competition sends tasks like "create order + invoice + payment" as one prompt. LLM must classify as `create_invoice` (not `create_order`).

4. **Product extraction** — Payment/reversal prompts mention products by name. LLM now extracts these into `orderLines`.

## What's Working Well

- Employee CRUD with employment
- Customer CRUD with org numbers
- Product creation with prices and numbers
- Department creation with manager
- Project creation with customer + employee
- Invoice full flow (order -> lines -> invoice -> payment)
- Project invoices (milestone/partial payments)
- Payment reversals
- Travel expenses with cost lines
- Supplier invoice vouchers with account resolution
- Activity creation
- 7-language support (handled naturally by Claude)

## Known Gaps / What to Work On Next

### Not yet battle-tested in competition:
- `update_customer` / `update_employee` — work in sandbox but not seen in competition
- `assign_role` — role assignment logic is basic
- `enable_module` — untested, may need specific module names
- `create_asset` / `update_asset` — untested in competition
- `bank_reconciliation` — handler exists but complex, untested
- `ledger_correction` — basic voucher creation, may need more
- `year_end_closing` — basic, likely needs specific closing entries
- `balance_sheet_report` — just a GET query
- `send_invoice` — needs invoice ID (may need to create first)
- `deliver_travel_expense` / `approve_travel_expense` — need travel expense ID

### Efficiency improvements:
- Invoice flow uses 8-11 API calls (optimal is 3). Biggest waste: bank account check (cached now), product lookups, payment type lookup.
- Voucher uses 5 calls (optimal 1) due to account lookups. Could cache account number->ID mappings.
- Every 4xx error reduces efficiency bonus. Pre-validate where possible.

### Tier 3 tasks (open Saturday, 3x multiplier):
- These are worth the most points. Prepare handlers for bank reconciliation, ledger corrections, year-end closing.
- Test against sandbox before they open.

## Sandbox Credentials

- **URL:** `https://kkpqfuj-amager.tripletex.dev/v2`
- **Token:** `eyJ0b2tlbklkIjoyMTQ3NjI5NjQ5LCJ0b2tlbiI6IjYzZWU1MTFlLTg2ZDAtNDk4Mi04NDY1LTFmZDIwNjBlNGE1ZSJ9`
- **Web UI:** `https://kkpqfuj-amager.tripletex.dev` (login: stianjp@hotmail.com)
- **Token expires:** March 31, 2026

## Quick Reference: Adding a New Handler

1. Create handler class in `src/handlers/yourfile.py`
2. Use `@register_handler` decorator
3. Implement `get_task_type()`, `required_params`, `execute()`
4. Import in `src/handlers/__init__.py`
5. Add task type to `src/constants.py` (`ALL_TASK_TYPES`)
6. Add to LLM system prompt in `src/llm.py`
7. Write sandbox integration test in `tests/test_all_handlers_sandbox.py`
8. Run tests, commit, deploy
