# Fix Competition Run

Analyze a competition run and implement fixes to achieve a **perfect score** (all checks passed).

## Trigger

Use when the user reports a competition score (e.g., "Task (2/10)") or asks to fix a failing run.

## Critical Scoring Context

**Perfect correctness (1.0) is the #1 priority.** The scoring system heavily rewards it:
- At 80% checks passed on Tier 2: score = 1.6
- At 100% checks passed on Tier 2: score = 2.0 minimum, up to **4.0** with efficiency bonus
- The efficiency bonus (up to 2x multiplier) ONLY unlocks at **exactly 100% correctness**
- Going from 9/10 to 10/10 checks can more than double your score

**Every single failed check matters.** A run with 1 failed check gets ZERO efficiency bonus.

**Prioritize by tier.** Fixing a Tier 3 task (x3 multiplier) is worth 3x more than a Tier 1 task (x1). When choosing what to fix first, always pick the highest-tier imperfect task.

**You cannot re-test the exact same scenario.** Each submission gets a random variant (different language, different dataset out of 56 combinations). You will never see the same prompt twice. This means all fixes must be **general** — they must work for any input, not just the values from the failing run.

## Process

### 1. Identify which checks passed/failed

Get the competition results from the leaderboard or user. For each task, determine:
- **Total checks** and **checks passed** (e.g., "8/10 checks passed")
- **Which specific checks failed** (e.g., "Correct email: FAIL", "Administrator role: FAIL")
- **The tier** of the task (Tier 1/2/3)

If the user provides a score like "Task X (8/10)", ask:
> "Which specific checks failed? Can you share the check breakdown from the results page?"

**If no per-check breakdown is available**, infer the likely failed checks by:
1. Reading the run logs (Step 2) to see what the handler actually did
2. Cross-referencing with known check patterns for that task type (see task check table below)
3. Looking for 4xx errors, missing fields, or wrong values in the API calls

**Triage by score range** — the debugging approach differs:
- **0/10 or very low**: Handler likely crashed, task wasn't classified, or entity wasn't created at all. Start by checking logs for exceptions and classification.
- **Partial (e.g., 5-8/10)**: Entity was created but some fields are wrong. Focus on field-level extraction and normalization.
- **Almost perfect (e.g., 9/10)**: One subtle field is wrong. Careful comparison of what was sent vs expected.

#### Known check patterns by task type

These are the fields typically verified per task type. Use this to infer which checks likely failed:

| Task Type | Typical Checks |
|-----------|---------------|
| create_employee | Entity found, firstName, lastName, email, role/permissions |
| create_customer | Entity found, name, email, phone, address |
| create_product | Entity found, name, number, price, vatType |
| create_invoice | Order found, customer, orderLines (product, count, price), invoice sent |
| register_payment | Payment found, amount, date, account |
| create_voucher | Voucher found, date, description, postings (account, amount, debit/credit) |
| travel_expense | Expense found, employee, date, amount, cost category, per diem details |
| create_project | Project found, name, customer link, start/end dates, project category |
| create_department | Entity found, name, department number |
| update_employee | Entity found, changed field matches expected value |

Note: Actual checks may vary. Use this as a starting point for inference when the breakdown isn't available.

### 2. Get the run logs

```bash
gcloud run services logs read tripletex-agent-2 \
    --project ai-nm26osl-1792 \
    --region europe-west1 \
    --limit 60
```

Find the COMPETITION_RUN log line and all subsequent Step/Handler/Error lines for the run.

### 3. Analyze EACH failed check

For every failed check, determine:
- **What field/value was expected** vs. **what we actually set**
- **Root cause**: LLM extraction issue, handler bug, missing normalization, or wrong API call?
- **Is this a pattern** that would affect other variants too?

Map failed checks to likely causes:

| Failed Check Pattern | Likely Root Cause |
|---------------------|-------------------|
| "Entity found" fails | Handler crashed, wrong endpoint, or entity not created |
| "Correct [field]" fails | LLM didn't extract it, or handler didn't set it |
| "Correct amount" fails | Currency/VAT/rounding issue |
| "Correct role/type" fails | Enum mapping wrong (e.g., "administrator" vs "ADMIN") |
| "Correct date" fails | Date format or timezone issue |
| "Correct account" fails | Account not found in sandbox, wrong fallback |
| "Correct VAT" fails | Wrong VAT type or missing VAT handling |

Common failure patterns:
- **Missing fields**: LLM didn't extract all fields from PDF
- **Wrong format**: LLM sent wrong data types (boolean debit, nested objects, string addresses)
- **Account not found**: Competition sandbox has different accounts than dev sandbox
- **VAT handling**: Wrong VAT type or missing VAT
- **Entity conflicts**: Email/name already exists
- **Amount mismatch**: Currency conversion, partial payment, VAT inclusion
- **Context not propagated**: Multi-step task lost customer/invoice ref between steps

### 4. Implement fixes targeting EVERY failed check

Fix the handler code in `src/handlers/` or services in `src/services/`.

**For each failed check, you must:**
1. Identify the exact code path that produces the wrong value
2. Fix it to produce the correct value
3. Verify the fix is **general**: ask "Would this fix also work if the name/amount/language were completely different?" If the answer is no, the fix is too narrow.

Focus on:
- Making the handler resilient to varied LLM output formats
- Adding fallbacks for missing data
- Fixing field-level precision issues

**Do not stop at "mostly fixed".** If 2 checks failed, both must be fixed. Partial improvement without perfect correctness gains almost nothing on the leaderboard.

### 5. Add a competition test

Add a test in `tests/test_competition_patterns.py` that:
- Uses the params from the failing run as a **regression test** (pinning this specific scenario)
- Verifies the handler produces the correct result
- **Checks EVERY field that the competition verifies** (not just the ones that failed)

Note: The test pins specific values for regression coverage. The handler code itself must be general — the test just ensures we don't re-break this case.

Pattern:
```python
class TestNewPattern:
    """Based on real X/Y failure: [description of what went wrong]."""

    def test_exact_scenario(self, client):
        tag = uid()
        result = run_handler(client, "task_type", {
            # Exact params from the failing run (regression pin)
        })
        assert result["id"]
        # Verify ALL competition-checked fields, not just the broken ones
```

### 6. Verify and deploy

```bash
# Run unit tests
python -m pytest tests/ -m "not slow" -q --tb=short

# Run the specific competition test
SANDBOX_URL=... SANDBOX_TOKEN=... python -m pytest tests/test_competition_patterns.py::TestNewPattern -v --tb=short

# Lint
ruff check src/ && ruff format src/ tests/

# Deploy (see full command at bottom of this file)
git add src/ tests/
git commit -m "Fix [task type]: [what was fixed]"
# Then run the deploy command from the "Deploy command" section below
```

### 7. Post-deploy: Monitor subsequent runs

After deploying, remind the user to:
1. **Submit the task type again** on the competition platform — it will be a **different random variant**
2. **Check the per-check breakdown** on the new run — did ALL checks pass?
3. **If a different check fails**, the fix was too narrow — repeat from Step 1 with the new failure

**The task isn't truly fixed until you see consistent perfect scores across multiple random variants.**

### 8. After perfect correctness: Optimize efficiency

Once a task type consistently hits 100% correctness, the next leaderboard gain comes from efficiency:

1. **Reduce write API calls** (POST/PUT/DELETE/PATCH) — only these count for efficiency scoring
2. **Eliminate 4xx errors** — each one reduces the efficiency bonus
3. **Compare against the handler's current write-call count** in the logs
4. **GETs are free for scoring** but add latency — only remove them if they don't contribute to correctness

This can up to **double** the score on a task that's already at perfect correctness.

### 9. Report

Tell the user:
- **Check summary**: Which checks were failing and what each fix was
- **Score impact estimate**: e.g., "Tier 2 task at 0.8 correctness → targeting 1.0 (score: 1.6 → 2.0+, up to 4.0 with efficiency)"
- What competition test was added
- That the fix is deployed
- **Remind**: Submit again and check the new variant's results — we need to see perfect scores on random variants to confirm the fix is general

## Key files

- `src/handlers/` — handler implementations
- `src/services/param_normalizer.py` — LLM output normalization
- `src/services/posting_builder.py` — voucher posting construction
- `src/handlers/entity_resolver.py` — entity find-or-create
- `src/task_router.py` — multi-step orchestration
- `tests/test_competition_patterns.py` — competition scenario tests

## Deploy command

```bash
gcloud builds submit --project ai-nm26osl-1792 --region europe-west1 \
  --tag europe-west1-docker.pkg.dev/ai-nm26osl-1792/cloud-run-source-deploy/tripletex-agent-2:latest \
  --timeout=600 && \
gcloud run deploy tripletex-agent-2 --project ai-nm26osl-1792 --region europe-west1 \
  --image europe-west1-docker.pkg.dev/ai-nm26osl-1792/cloud-run-source-deploy/tripletex-agent-2:latest \
  --platform managed --allow-unauthenticated --port 8080 --timeout 300 \
  --memory 512Mi --cpu 1 --min-instances 0 --max-instances 10 --concurrency 1 \
  --set-env-vars "ANTHROPIC_VERTEX_PROJECT_ID=ai-nm26osl-1792,CLOUD_ML_REGION=us-east5"
```
