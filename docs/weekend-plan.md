# Weekend Plan: Friday Evening - Sunday Evening

**Deadline:** Sunday March 22, evening
**Current state:** 28/30 handlers, live on Cloud Run, scoring 5-8/8 on most tasks
**Goal:** Maximize total leaderboard score across all 30 task types

---

## Scoring Refresher

```
task_score = correctness * tier_multiplier * (1 + efficiency_bonus)
```

- Efficiency bonus ONLY unlocks at correctness = 1.0
- Best score per task kept forever (can never go down)
- Efficiency benchmarks recalculated every 12h
- Tier 3 tasks open Saturday (x3 multiplier, up to 6.0 pts each)
- 30 task types total, we cover 28

---

## Priority Matrix (ROI: points per hour)

| Priority | Item | Est. Points | Est. Hours | ROI |
|----------|------|-------------|------------|-----|
| P0 | Add 2 missing task types | 2-6 pts | 1h | 3.0 |
| P0 | Fix LLM classification reliability | +2-5 pts | 2h | 1.75 |
| P1 | Tier 3 handler hardening | 6-18 pts | 3h | 4.0 |
| P1 | Cache payment types / cost categories | +1-3 pts | 1h | 2.0 |
| P2 | Reduce API calls in invoice handler | +0.5-2 pts | 2h | 0.75 |
| P2 | Reduce API calls in travel handler | +0.3-1 pts | 1.5h | 0.5 |
| P3 | Switch to tool_use for classification | +1-2 pts | 3h | 0.5 |
| P3 | Bank reconciliation account resolution | +1-3 pts | 2h | 1.0 |

---

## Phase 1: Friday Evening (3-4 hours)

### 1.1 Add Missing Task Types [P0, 1 hour]

**What:** The competition has 30 task types but we only define 28. Two candidates:
- `delete_travel_expense` -- GET /travelExpense (search) then DELETE /travelExpense/{id}
- `delete_voucher` -- GET /ledger/voucher (search) then DELETE /ledger/voucher/{id}

**Files to change:**
- `src/constants.py` -- add to TIER_2_TASKS or TIER_3_TASKS and OPTIMAL_CALL_COUNTS
- `src/handlers/travel.py` -- add DeleteTravelExpenseHandler class
- `src/handlers/ledger.py` -- add DeleteVoucherHandler class
- `src/llm.py` -- add to SYSTEM_PROMPT parameter schemas

**Implementation pattern (both are identical):**
```python
@register_handler
class DeleteTravelExpenseHandler(BaseHandler):
    def get_task_type(self) -> str:
        return "delete_travel_expense"

    @property
    def required_params(self) -> list[str]:
        return []

    def execute(self, api_client, params):
        te_id = params.get("travelExpenseId")
        if not te_id:
            # Search by employee name or other criteria
            search_params = {"count": 1}
            if params.get("employee"):
                emp_ref = _resolve_employee(api_client, params["employee"])
                search_params["employeeId"] = emp_ref["id"]
            resp = api_client.get("/travelExpense", params=search_params)
            values = resp.get("values", [])
            if not values:
                return {"error": "not_found"}
            te_id = values[0]["id"]
        api_client.delete(f"/travelExpense/{int(te_id)}")
        return {"id": te_id, "action": "deleted"}
```

**Expected impact:** 2-6 points (currently scoring 0 on these task types)
**Test:** Submit 2-3 times and check leaderboard for new task scores

### 1.2 LLM Classification Hardening [P0, 2 hours]

**Problem validated:** The SYSTEM_PROMPT in `src/llm.py` (line 32-89) is a monolithic blob with all 28+ task types inlined. Key risks:
- No few-shot examples for confusing pairs
- No multilingual keyword support
- JSON parsing can fail (markdown fences, arrays)
- `LLM_MAX_TOKENS = 2048` wastes tokens on classification (response is ~50 tokens)

**Changes:**

#### 1.2a: Reduce LLM_MAX_TOKENS (5 min)
- File: `src/constants.py` line 71
- Change: `LLM_MAX_TOKENS = 2048` to `LLM_MAX_TOKENS = 1024`
- Why: Classification response is ~50 tokens JSON. 1024 is plenty and saves latency/cost.

#### 1.2b: Add multilingual keywords to system prompt (30 min)
- File: `src/llm.py` SYSTEM_PROMPT
- Add glossary block:
```
MULTILINGUAL KEYWORDS:
- faktura/invoice/factura/Rechnung/facture = invoice
- bestilling/order/Bestellung/commande = order
- ansatt/employee/Mitarbeiter/empleado = employee
- kunde/customer/Kunde/cliente = customer
- produkt/product/Produkt/producto = product
- reiseregning/travel expense/Reisekostenabrechnung = travel expense
- bilag/voucher/Beleg/comprobante = voucher
- leverandorfaktura/supplier invoice = create_voucher (NOT create_invoice)
- kreditnota/credit note/Gutschrift = credit_note
- betaling/payment/Zahlung/pago = payment
- slett/delete/loschen/eliminar = delete
```

#### 1.2c: Add disambiguation rules (30 min)
- File: `src/llm.py` SYSTEM_PROMPT
- Add after CLASSIFICATION RULES:
```
DISAMBIGUATION:
- "slett reiseregning" / "delete travel expense" = delete_travel_expense
- "slett bilag" / "delete voucher" = delete_voucher
- "leverandorfaktura" / "supplier invoice" = create_voucher (NOT create_invoice)
- "registrer betaling" + negative amount or "reversering" = register_payment with reversal=true
- "arsoppgjor" / "year-end closing" = year_end_closing
- "bankavstemming" / "bank reconciliation" = bank_reconciliation
- Task mentions BOTH order AND invoice = create_invoice (not create_order)
- Task mentions ONLY order (no invoice/faktura) = create_order
```

#### 1.2d: Improve JSON parsing robustness (15 min)
- File: `src/llm.py` `_parse_response` method (line 206-229)
- Add regex fallback to extract JSON from any text wrapping
- Validate task_type against ALL_TASK_TYPES, fuzzy-match if not exact

**Expected impact:** +2-5 points from fewer misclassifications

### 1.3 First Submission Round [15 min]

After 1.1 and 1.2 are deployed:
- `git commit` and push
- Trigger Cloud Run deployment
- Submit 3 times to establish baseline scores for all 30 task types
- Note which tasks score below 1.0 correctness for Saturday investigation

---

## Phase 2: Saturday Morning (3-4 hours)

### 2.1 Tier 3 Handler Hardening [P1, 3 hours]

Tier 3 opens Saturday. Each task worth up to 6.0 points. Six Tier 3 task types:

#### 2.1a: BankReconciliationHandler -- fix account resolution (1 hour)
- File: `src/handlers/bank.py`
- **Problem validated:** Handler requires `accountId` (line 26) but prompts give account numbers (e.g., "1920")
- **Fix:** Change `required_params` to `[]`. Add account number resolution at start of `execute()`:
```python
if "accountId" not in params and "account" in params:
    acct_num = params["account"]
    resp = api_client.get("/ledger/account",
        params={"number": str(acct_num), "count": 1}, fields="id")
    values = resp.get("values", [])
    if values:
        params["accountId"] = values[0]["id"]
```
- Also resolve `accountingPeriodId` from date if not provided -- GET /timesheet/settings to find current period
- **LLM fix:** Update SYSTEM_PROMPT to extract account number as `account` param for bank_reconciliation

#### 2.1b: YearEndClosingHandler -- auto-generate closing entries (1 hour)
- File: `src/handlers/reporting.py` lines 70-107
- **Problem validated:** Handler just creates a voucher with whatever postings the LLM extracts. If LLM misses postings, the closing is incomplete.
- **Fix:** If no postings provided, fetch balance sheet and generate standard closing entries:
  1. GET /resultBudget or /balanceSheet for the year
  2. Create postings to zero out P&L accounts (3000-8999) against equity (8800/2050)
- **LLM fix:** Update SYSTEM_PROMPT to extract `year` from "arsoppgjor 2025" type prompts

#### 2.1c: CreateVoucherHandler -- improve posting extraction (30 min)
- File: `src/handlers/ledger.py`
- **Already good** but verify edge cases:
  - Supplier invoice with debit on expense account + credit on accounts payable (2400)
  - Postings with explicit VAT amounts
  - Account number resolution already works via `_resolve_account`

#### 2.1d: LedgerCorrectionHandler -- verify correction flow (30 min)
- File: `src/handlers/reporting.py` lines 16-66
- Verify: if `originalVoucherId` missing, handler creates correction voucher anyway (good)
- Add fallback: search for original voucher by date + description if ID not given

### 2.2 Submit After Tier 3 Hardening [15 min]

- Deploy and submit 3-5 times
- Check Tier 3 scores specifically
- Note any 0-score tasks for immediate fixing

---

## Phase 3: Saturday Afternoon (3-4 hours)

### 3.1 Cache Frequently-Fetched Data [P1, 1 hour]

**Problem validated:** Payment type lookup happens in both `CreateInvoiceHandler` (line 266-270) and `RegisterPaymentHandler` (line 374-378). Cost categories are fetched per travel expense.

**Changes:**
- File: `src/api_client.py` -- add caching layer to TripletexClient
```python
def __init__(self, ...):
    ...
    self._cache: dict[str, Any] = {}

def get_cached(self, key: str, endpoint: str, params: dict, fields: str) -> Any:
    if key not in self._cache:
        self._cache[key] = self.get(endpoint, params=params, fields=fields)
    return self._cache[key]
```
- File: `src/handlers/invoice.py` -- use cached payment type lookup
- File: `src/handlers/travel.py` -- use cached cost category + payment type
- **Saves:** 1-2 API calls per invoice task, 1-2 per travel task

### 3.2 Reduce Invoice Handler API Calls [P2, 2 hours]

**Problem validated:** CreateInvoiceHandler flow (line 146-286):
1. `_ensure_bank_account` -- 1-2 calls (GET account + optional PUT) -- cached after first run
2. `_resolve_customer` -- 1-2 calls (GET search + optional POST create)
3. POST /order -- 1 call
4. Per product: GET /product (search) + optional POST /product (create) -- 1-2 calls EACH
5. POST /order/orderline/list -- 1 call (batch, good)
6. POST /invoice -- 1 call
7. Optional payment: GET /invoice/paymentType + PUT /:payment -- 2 calls

**Total:** 8-11 calls. **Optimal:** 3 calls (POST order + POST lines + POST invoice).

**Reductions:**
1. Skip `_ensure_bank_account` after first successful invoice (already cached, but verify)
2. Skip customer search if LLM extracts customer ID directly
3. Skip product search -- just create products inline without searching first (saves 1 GET per product)
4. Cache payment type ID
5. For product creation, never send `priceExcludingVatCurrency` (avoid the VAT retry that wastes a 400 error call)

**File changes:**
- `src/handlers/invoice.py` -- `_resolve_product`: try create first, skip search when name is provided
- `src/handlers/invoice.py` -- CreateInvoiceHandler.execute: cache payment type

### 3.3 Reduce Travel Handler API Calls [P2, 1 hour]

**Problem validated:** CreateTravelExpenseHandler flow (line 156-271):
1. `_resolve_employee` -- 1-2 calls
2. POST /travelExpense -- 1 call
3. Per cost: GET /travelExpense/paymentType + GET /travelExpense/costCategory + POST /travelExpense/cost -- 3 calls each
4. Optional per diem: POST /travelExpense/perDiemCompensation -- 1 call

**Total:** 4-8+ calls. **Optimal:** 1 call.

**Reductions:**
1. Cache payment type (line 132-142) -- move to client-level cache
2. Cache cost categories (already has `_cache` dict in `_find_cost_category`, but it resets per call)
3. Batch cost creation if API supports it

**File changes:**
- `src/handlers/travel.py` -- pass cat_cache between calls (already works), cache payment type at module level

### 3.4 Submit Round [15 min]

- Deploy and submit 5 times
- Compare scores against Phase 1 baseline
- Identify remaining low-scoring tasks

---

## Phase 4: Saturday Evening (2-3 hours)

### 4.1 Fix Specific Failing Tasks [P1, 2 hours]

Based on submission results, fix the lowest-scoring tasks. Common failure patterns:

#### Pattern A: Wrong task classification
- Symptom: Score 0 on a task type that has a handler
- Fix: Add specific keywords/rules to SYSTEM_PROMPT
- File: `src/llm.py`

#### Pattern B: Missing required field
- Symptom: Handler runs but API returns 400
- Fix: Add defaults or resolve missing fields
- Investigate: Check Cloud Run logs for validation error details

#### Pattern C: Wrong API call sequence
- Symptom: Handler runs, calls succeed, but score is low
- Fix: Adjust handler logic based on what the scoring system expects
- Example: balance_sheet_report might need to POST something, not just GET

### 4.2 Error Cleanliness Pass [P2, 1 hour]

Efficiency bonus penalizes 4xx errors. Common sources:
1. Product creation with price causing VAT 400 retry (line 121-126 in invoice.py) -- remove price from product body entirely
2. Bank account check on 1920 failing -- cache result, skip if already checked
3. Employee creation needing department retry (line 64-75 in employee.py) -- pre-fetch department

**File changes:**
- `src/handlers/invoice.py` `_resolve_product` -- never send price, always set on order line
- `src/handlers/employee.py` -- pre-fetch department before POST

### 4.3 Submit Round [15 min]

- Submit 3 times
- Verify error reduction shows in scores

---

## Phase 5: Sunday Morning (3-4 hours)

### 5.1 Tool_use Migration for Classification [P3, 3 hours]

**Why:** Guarantees valid JSON output and constrains task_type to known values. Eliminates JSON parsing failures entirely.

**Changes:**
- File: `src/llm.py`
- Replace `system` prompt + text response with `tool_use`:
```python
tools = [{
    "name": "classify_task",
    "description": "Classify accounting task and extract parameters",
    "input_schema": {
        "type": "object",
        "properties": {
            "task_type": {"type": "string", "enum": ALL_TASK_TYPES},
            "params": {"type": "object"}
        },
        "required": ["task_type", "params"]
    }
}]
```
- Update `classify_and_extract` to use `tool_choice={"type": "tool", "name": "classify_task"}`
- Parse `response.content[0].input` instead of text
- Remove all JSON parsing fallbacks (no longer needed)

**Expected impact:** +1-2 points from eliminating classification failures

### 5.2 Targeted Fix Round [P1, 1 hour]

Based on all submission data so far, fix the 2-3 lowest-scoring tasks with targeted changes.

---

## Phase 6: Sunday Afternoon/Evening (3-4 hours)

### 6.1 Final Optimization Pass [1 hour]

- Review API call counts in logs for each task type
- Remove any remaining unnecessary GET calls
- Verify no 4xx errors in clean runs

### 6.2 Stress Testing [1 hour]

- Submit 10+ times rapidly
- Verify consistency (same task should score the same every time)
- Check for rate limiting issues
- Verify timeout handling (300s limit)

### 6.3 Final Submissions [2 hours]

- Submit every 15-20 minutes for the last 2 hours
- Best score per task is kept, so more submissions = more chances
- Monitor for any score regressions (shouldn't happen since best is kept)
- If a task scores 0, investigate and fix immediately

---

## Submission Strategy

| When | Submissions | Purpose |
|------|-------------|---------|
| Friday 23:00 | 3x | Baseline for all 30 tasks |
| Saturday 10:00 | 3x | After Tier 3 hardening |
| Saturday 14:00 | 5x | After efficiency improvements |
| Saturday 20:00 | 3x | After error cleanliness pass |
| Sunday 10:00 | 3x | After tool_use migration |
| Sunday 14:00-18:00 | 10-15x | Final push, every 15-20 min |

**Total:** 27-32 submissions across the weekend

**Key rule:** Submit often. Each submission is independent (fresh sandbox). Best score kept forever. There is zero downside to submitting more.

---

## Minimum Viable Weekend (if time runs short)

If you can only do 4 hours total, do ONLY these:

1. **Add 2 missing task types** (1h) -- guaranteed new points from 0 to something
2. **Fix BankReconciliationHandler account resolution** (30min) -- Tier 3, worth up to 6 pts
3. **Add multilingual keywords to LLM prompt** (30min) -- prevents misclassification
4. **Reduce LLM_MAX_TOKENS to 1024** (5min) -- free latency improvement
5. **Remove price from product creation** (15min) -- eliminates wasted 400 error
6. **Submit 10 times** (spread over remaining time)

This minimum set targets ~5-10 additional points with minimal risk.

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Deployment breaks | Test locally before every push; keep rollback commit hash |
| Tier 3 tasks have unknown format | Submit early Saturday to see actual prompts in logs |
| LLM changes cause regressions | Run integration tests before deploying; keep old prompt as fallback |
| Rate limiting | Add jitter to retry delays; don't submit more than 1x per 5 min |
| Running out of time | Follow minimum viable weekend list above |

---

## Key File Reference

| File | Lines | What to change |
|------|-------|----------------|
| `src/constants.py` | 71, 90-131, 137-169 | LLM_MAX_TOKENS, task type lists, optimal call counts |
| `src/llm.py` | 32-89, 206-229 | System prompt, JSON parsing |
| `src/handlers/invoice.py` | 89-129, 146-286, 266-284 | Product resolution, invoice flow, payment caching |
| `src/handlers/travel.py` | 132-142, 156-271 | Payment type caching, cost flow |
| `src/handlers/ledger.py` | (new class) | DeleteVoucherHandler |
| `src/handlers/bank.py` | 25-29 | Account number resolution |
| `src/handlers/reporting.py` | 70-107 | Year-end closing auto-generation |
| `src/handlers/employee.py` | 64-75 | Pre-fetch department |
| `src/api_client.py` | 42-49 | Add caching layer |
