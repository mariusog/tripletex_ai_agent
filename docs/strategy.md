# Strategy: Winning the Tripletex Challenge

## Scoring Math - Where the Points Are

### Maximum Theoretical Score: 180 points

```
30 tasks x 6.0 max per task = 180.0

Breakdown by tier:
- Tier 1 tasks: max 2.0 each (1.0 correctness x 1 multiplier x 2 efficiency)
- Tier 2 tasks: max 4.0 each (1.0 correctness x 2 multiplier x 2 efficiency)
- Tier 3 tasks: max 6.0 each (1.0 correctness x 3 multiplier x 2 efficiency)
```

**Key insight:** Tier 3 tasks are worth 3x Tier 1. But efficiency bonus only unlocks at 100% correctness. Therefore:

> **Priority 1:** Get 100% correctness on ALL tasks.
> **Priority 2:** Minimize API calls and eliminate 4xx errors.
> **Priority 3:** Tackle Tier 3 tasks as soon as they open (Saturday).

## Architecture

### High-Level Flow

```
POST /solve
  -> Parse request (prompt, files, credentials)
  -> LLM: Classify task type from prompt
  -> LLM: Extract structured parameters (names, amounts, dates, etc.)
  -> Execute task-specific handler (deterministic API call sequence)
  -> Verify result via GET calls
  -> Return {"status": "completed"}
```

### Two-Phase Design

**Phase 1: LLM Interpretation**
- Use an LLM to parse the natural-language prompt
- Extract: task type, entity names, field values, amounts, dates
- Handle 7 languages (the LLM handles this naturally)
- Decode and interpret file attachments (PDF receipts, images)

**Phase 2: Deterministic Execution**
- Each task type maps to a hardcoded, optimal API call sequence
- No trial-and-error - plan the exact calls needed
- This is critical for efficiency score (fewer calls = higher bonus)

### Why This Split Matters

- LLM handles language/parsing flexibility
- Hardcoded handlers ensure minimal API calls (maximum efficiency bonus)
- Errors from bad API calls are deterministic and fixable
- Each handler can be independently tested and optimized

## Implementation Plan

### Phase 1: Foundation (Hours 0-4)

1. **FastAPI endpoint** (`/solve`) with proper request/response models
2. **Tripletex API client** with Basic Auth, error handling, rate limit awareness
3. **LLM integration** (Claude or Gemini via Vertex AI) for prompt parsing
4. **Task classifier** - determine which of the 30 task types the prompt describes
5. **Deploy to Cloud Run** for HTTPS endpoint

### Phase 2: Tier 1 Tasks (Hours 4-10)

Tier 1 tasks are the simplest - nail these first for a solid base score.

Likely Tier 1 tasks and their API sequences:

| Task | Likely API Calls |
|------|-----------------|
| Create employee | POST `/employee` |
| Create customer | POST `/customer` |
| Create product | POST `/product` |
| Create department | POST `/department` |
| Create project | POST `/project` |
| Update employee contact | GET `/employee` + PUT `/employee/{id}` |

**Strategy per task:**
1. Use sandbox to manually perform the task via UI
2. Observe what API calls the UI makes (browser dev tools)
3. Replicate the minimal call sequence in the handler
4. Test against sandbox, verify with GET calls
5. Submit and iterate based on scoring feedback

### Phase 3: Tier 2 Tasks (Hours 10-20)

Multi-step workflows requiring chained API calls:

| Task | Likely API Calls |
|------|-----------------|
| Create invoice | POST `/order` + POST `/order/orderline` + POST `/invoice` |
| Register payment | GET `/invoice` + POST `/invoice/{id}/:payment` |
| Create credit note | GET `/invoice` + POST `/invoice/{id}/:createCreditNote` |
| Travel expense | POST `/travelExpense` + POST `/travelExpense/:deliver` |
| Link project to customer | POST `/project` with customer reference |

### Phase 4: Tier 3 Tasks (Saturday)

Complex workflows - prepare handlers in advance:

| Task | Likely API Calls |
|------|-----------------|
| Bank reconciliation | Multiple reconciliation endpoints |
| Ledger corrections | POST `/ledger/voucher` + POST `/ledger/voucher/:reverse` |
| Year-end closing | Multiple ledger operations |

### Phase 5: Efficiency Optimization (Ongoing)

Once correctness is 100%:
1. Audit each handler for unnecessary GET calls
2. Remove any exploratory/validation calls that aren't needed
3. Use batch endpoints (`/list`) where available
4. Profile API call counts per task vs. leaderboard benchmarks
5. Eliminate all 4xx errors - validate inputs before sending

## Key Technical Decisions

### LLM Choice
- **Claude** (via API): Best at structured extraction, handles all 7 languages well
- **Gemini** (via Vertex AI): Free on GCP, good enough for task classification
- **Recommendation:** Use Claude for complex extraction, consider Gemini as fallback for cost

### Task Classification Approach

Option A: **LLM classification** - send prompt to LLM, ask it to classify into one of 30 types
Option B: **Keyword matching** - faster, cheaper, but fragile across languages
**Recommendation:** Option A. LLM handles languages naturally and the cost per call is negligible vs. the 5-minute timeout.

### Parameter Extraction

Use structured output (JSON mode) to extract:
```json
{
  "task_type": "create_employee",
  "params": {
    "first_name": "Ola",
    "last_name": "Nordmann",
    "email": "ola@example.com",
    "role": "administrator"
  }
}
```

### Error Handling
- Parse Tripletex error responses for `validationMessages`
- Retry on 429 (rate limit) with backoff
- Do NOT retry on 4xx - fix the root cause (4xx errors hurt efficiency score)
- Log all API interactions for debugging

## Competitive Advantages to Build

1. **Speed:** Pre-compute the exact API call sequence per task type. No exploration needed at runtime.
2. **Zero errors:** Validate all inputs before API calls. Know the required fields for each endpoint.
3. **File handling:** Many competitors will skip PDF/image attachments. Parse them with LLM vision.
4. **Language robustness:** Test with all 7 languages, not just English/Norwegian.
5. **Tier 3 readiness:** Build handlers before Saturday so you can submit immediately when Tier 3 opens.

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| LLM hallucination on task type | Use few-shot examples with all 30 task types |
| Unknown Tripletex API quirks | Explore sandbox thoroughly, try all operations manually first |
| Rate limiting | Queue submissions, respect limits, use exponential backoff |
| Timeout (5 min) | Profile each handler, set per-step timeouts |
| Norwegian characters breaking | Ensure UTF-8 everywhere, test with ae/oe/aa |
| File attachments | Implement base64 decode + LLM vision for PDFs/images |
| Fresh account edge cases | Test handler with empty account state |

## Iteration Loop

```
1. Pick a task type
2. Read sandbox API to understand required fields
3. Build handler with minimal API calls
4. Test locally against sandbox
5. Submit to competition
6. Read scoring feedback
7. Fix correctness issues
8. Optimize efficiency (remove unnecessary calls)
9. Repeat
```

## Quick Win Priorities

1. Employee CRUD (likely simplest, Tier 1)
2. Customer CRUD (similar pattern)
3. Product creation (similar pattern)
4. Department/Project creation (similar pattern)
5. Invoice creation (Tier 2, high multiplier)
6. Payment registration (Tier 2, high multiplier)

Getting 100% on even 10 Tier 1+2 tasks puts you on the leaderboard fast.
