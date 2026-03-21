# Fix Competition Run

Analyze the latest competition run failure and implement fixes to achieve a perfect score.

## Trigger

Use when the user reports a competition score (e.g., "Task (2/10)") or asks to fix a failing run.

## Process

### 1. Get the latest run logs

```bash
gcloud run services logs read tripletex-agent-2 \
    --project ai-nm26osl-1792 \
    --region europe-west1 \
    --limit 60
```

Find the COMPETITION_RUN log line and all subsequent Step/Handler/Error lines for the run.

### 2. Analyze the failure

From the logs, determine:
- What task type was it? (e.g., create_employee, create_voucher)
- How many steps were there?
- Did any steps fail? What errors?
- What params did the LLM extract?
- What checks likely failed and why?

Common failure patterns:
- **Missing fields**: LLM didn't extract all fields from PDF
- **Wrong format**: LLM sent wrong data types (boolean debit, nested objects, string addresses)
- **Account not found**: Competition sandbox has different accounts
- **VAT handling**: Wrong VAT type or missing VAT
- **Entity conflicts**: Email/name already exists
- **Amount mismatch**: Currency conversion, partial payment, VAT inclusion
- **Context not propagated**: Multi-step task lost customer/invoice ref between steps

### 3. Implement the fix

Fix the handler code in `src/handlers/` or services in `src/services/`.
Focus on:
- Making the handler resilient to the specific LLM output format seen
- Adding fallbacks for missing data
- Fixing field-level precision issues

### 4. Add a competition test

Add a test in `tests/test_competition_patterns.py` that:
- Reproduces the exact params from the failing run
- Verifies the handler produces the correct result
- Checks specific field values the competition verifies

Pattern:
```python
class TestNewPattern:
    """Based on real X/Y failure: [description of what went wrong]."""

    def test_exact_scenario(self, client):
        tag = uid()
        result = run_handler(client, "task_type", {
            # Exact params from the failing run
        })
        assert result["id"]
        # Verify specific fields
```

### 5. Verify and deploy

```bash
# Run unit tests
python -m pytest tests/ -m "not slow" -q --tb=short

# Run the specific competition test
SANDBOX_URL=... SANDBOX_TOKEN=... python -m pytest tests/test_competition_patterns.py::TestNewPattern -v --tb=short

# Lint
ruff check src/ && ruff format src/ tests/

# Deploy
git add src/ tests/
git commit -m "Fix [task type]: [what was fixed]"
gcloud builds submit ... && gcloud run deploy ...
```

### 6. Report

Tell the user:
- What the root cause was
- What was fixed
- What competition test was added
- That the fix is deployed

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
