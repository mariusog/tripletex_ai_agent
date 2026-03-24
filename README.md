# Tripletex AI Agent

An AI-powered agent that interprets natural language accounting prompts and executes them against the [Tripletex](https://www.tripletex.no/) API. Built for the [NM i AI 2026](https://www.nmiai.no/) Tripletex challenge.

## Competition

**Challenge:** Receive natural language accounting prompts in 7 languages, execute them against a fresh Tripletex sandbox via REST API. Scored on correctness (did every field pass validation?), task tier (complexity multiplier), and efficiency (fewer API calls = bonus).

**Scoring:** `correctness * tier_multiplier * (1 + efficiency_bonus)` -- the efficiency bonus only unlocks at 100% correctness, making perfect field values the top priority.

## Solution

### Architecture: LLM Classifies, Handlers Execute

The core design decision was separating the hard problem (understanding natural language) from the deterministic problem (making API calls):

## How It Works

```
POST /solve  { "prompt": "Create an invoice for Acme Corp for 5000 kr" }
       |
       v
  LLM (Claude via Vertex AI)
    - Classifies task type (1 of 28 registered handlers)
    - Extracts structured params (names, amounts, dates, accounts)
       |
       v
  TaskRouter -> Handler
    - Deterministic Tripletex API calls
    - Auto-creates prerequisite entities (customer, employee, product, etc.)
    - Returns structured result
```

The agent handles 28 task types across the full Tripletex accounting domain:

| Category | Tasks |
|----------|-------|
| **Entities** | Create/update/delete employees, customers, suppliers, products, departments, projects |
| **Invoicing** | Create invoices, send, register payments, credit notes |
| **Accounting** | Create/reverse/delete vouchers, ledger corrections, year-end closing, balance sheet reports |
| **Payroll** | Run payroll, log timesheets |
| **Travel** | Create/deliver/approve/delete travel expenses |
| **Other** | Bank reconciliation, cost analysis, asset management, enable modules, assign roles |

### Key Design Decisions

**Handler registry pattern** -- Each of the 28 task types is a handler class decorated with `@register_handler`. Handlers declare their tier, parameter schema, and disambiguation rules. The LLM system prompt is built dynamically from handler metadata -- adding a new task type means creating one file, no routing changes needed.

**Metadata-driven LLM prompt** -- The system prompt includes all 28 task types with their parameter schemas, grouped by tier. Claude classifies the task, extracts structured parameters via tool use, and returns JSON. Multi-step prompts (e.g., "create an invoice and register payment") are decomposed into a task array with context injection between steps.

**Entity resolution with find-or-create** -- Shared resolver functions (`_resolve_customer`, `_resolve_product`, etc.) search for existing entities by name and create them if missing. This handles the competition's fresh-account constraint where prerequisite entities don't exist yet.

**Efficiency through pre-planned sequences** -- Each handler has a known-optimal API call sequence. No trial-and-error, no exploratory GETs. Bank account lookups are cached, batch endpoints are used where possible, and unnecessary verification calls are eliminated.

### What Worked and What Didn't

| Decision | Outcome |
|----------|---------|
| LLM classification + deterministic handlers | Clean separation, independently testable, scales to 28+ types |
| Dynamic system prompt from handler metadata | New task types integrate without touching LLM code |
| Multi-step context injection | Essential for order -> invoice -> payment flows |
| Exact name matching over Tripletex fuzzy search | Prevented wrong entity lookups (API returns fuzzy matches by default) |
| Correctness-first strategy (ignore efficiency until 100%) | Right call -- efficiency bonus is gated on perfect correctness |
| Per-handler sandbox testing | Caught non-obvious API quirks (bank account required on account 1920, dateOfBirth required on updates, VAT on voucher postings) |

## Quick Start

```bash
pip install -e ".[dev]"

# Set required environment variables
export GCP_PROJECT_ID="your-gcp-project"
export SANDBOX_TOKEN="your-tripletex-sandbox-token"

# Run the server locally
uvicorn src.server:app --host 0.0.0.0 --port 8080

# Run tests
python -m pytest tests/ -m "not slow" -q --tb=line
```

## Project Structure

```
src/
  server.py          # FastAPI application (POST /solve endpoint)
  task_router.py     # LLM-powered task classification and parameter extraction
  llm.py             # Claude/Gemini integration via Vertex AI
  api_client.py      # Tripletex API client with auth and error handling
  models.py          # Pydantic request/response models
  constants.py       # All configuration and tuning parameters
  handlers/          # 28 task-specific handlers
    base.py          # BaseHandler with param schema and execution pattern
    employee.py      # Create/update employee
    invoice.py       # Create invoice, register payment, send
    reporting.py     # Year-end closing, balance sheet
    bank.py          # Bank reconciliation, customer/supplier payments
    ...
  services/          # Shared business logic (posting builder, param normalizer)
tests/               # Unit and integration tests
scripts/             # Simulation, competition testing, run capture
docs/                # API docs, sandbox setup, strategy
Dockerfile           # Multi-stage production image for Cloud Run
deploy.sh            # Cloud Run deployment script
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run fast tests
python -m pytest tests/ -m "not slow" -q --tb=line

# Lint and format
ruff check .
ruff format .

# Type check
mypy src/ --ignore-missing-imports

# Simulate all 28 task types against sandbox
python scripts/sim_all_tasks.py --service-url http://localhost:8080
```

## Deployment

The agent runs on Google Cloud Run. To deploy:

1. Update `deploy.sh` with your GCP project ID and region
2. Run `bash deploy.sh`

Or build the Docker image directly:

```bash
docker build -t tripletex-agent .
docker run -p 8080:8080 -e GCP_PROJECT_ID=your-project tripletex-agent
```

## Requirements

- Python 3.11+
- FastAPI, uvicorn
- httpx (Tripletex API client)
- pydantic (request/response models)
- anthropic SDK (LLM integration)
- google-cloud-aiplatform (Vertex AI)

## License

MIT
