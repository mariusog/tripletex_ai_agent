"""Named constants and tuning parameters for the Tripletex AI Agent.

All numeric thresholds, limits, and configuration values live here.
No magic numbers in logic code -- reference these constants instead.
"""

# ---------------------------------------------------------------------------
# Competition parameters
# ---------------------------------------------------------------------------

# Total time allowed per submission (seconds)
SUBMISSION_TIMEOUT = 300

# Number of task types in the competition
TOTAL_TASK_TYPES = 30

# Supported languages for prompts
SUPPORTED_LANGUAGES = [
    "norwegian",
    "english",
    "spanish",
    "portuguese",
    "nynorsk",
    "german",
    "french",
]

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

TIER_MULTIPLIERS = {
    1: 1.0,
    2: 2.0,
    3: 3.0,
}

# ---------------------------------------------------------------------------
# API client configuration
# ---------------------------------------------------------------------------

# Tripletex API Basic Auth username (always "0")
API_AUTH_USERNAME = "0"

# Default page size for list endpoints
API_DEFAULT_PAGE_SIZE = 100

# Maximum retries for rate-limited requests (429)
API_RATE_LIMIT_MAX_RETRIES = 3

# Base delay for exponential backoff on 429 (seconds)
API_RATE_LIMIT_BASE_DELAY = 1.0

# HTTP request timeout (seconds)
API_REQUEST_TIMEOUT = 30

# Default content type for API requests
API_CONTENT_TYPE = "application/json"

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------

# Maximum time to wait for LLM response (seconds)
LLM_TIMEOUT = 30

# Number of retries for transient LLM failures
LLM_MAX_RETRIES = 1

# Maximum tokens for LLM response
LLM_MAX_TOKENS = 1024

# Model identifiers
LLM_CLAUDE_MODEL = "claude-sonnet-4-20250514"
LLM_GEMINI_MODEL = "gemini-2.0-flash"

# Temperature for task classification (low = more deterministic)
LLM_TEMPERATURE = 0.0

# Vertex AI configuration (Claude via GCP)
LLM_VERTEX_MODEL = "claude-opus-4-6"
LLM_VERTEX_PROJECT_ID = "ai-nm26osl-1792"
LLM_VERTEX_REGION = "us-east5"

# ---------------------------------------------------------------------------
# Task types (known from competition docs)
# ---------------------------------------------------------------------------

# Tier 1 task types (x1 multiplier, simple CRUD)
TIER_1_TASKS = [
    "create_employee",
    "update_employee",
    "create_customer",
    "update_customer",
    "create_product",
    "create_department",
    "create_project",
    "assign_role",
    "enable_module",
]

# Tier 2 task types (x2 multiplier, multi-step)
TIER_2_TASKS = [
    "create_order",
    "create_invoice",
    "send_invoice",
    "register_payment",
    "create_credit_note",
    "create_travel_expense",
    "deliver_travel_expense",
    "approve_travel_expense",
    "delete_travel_expense",
    "link_project_customer",
    "create_activity",
    "update_project",
    "create_asset",
    "update_asset",
]

# Tier 3 task types (x3 multiplier, complex workflows, opens Saturday)
TIER_3_TASKS = [
    "create_voucher",
    "reverse_voucher",
    "delete_voucher",
    "bank_reconciliation",
    "ledger_correction",
    "year_end_closing",
    "balance_sheet_report",
]

# All known task types
ALL_TASK_TYPES = TIER_1_TASKS + TIER_2_TASKS + TIER_3_TASKS

# ---------------------------------------------------------------------------
# Optimal API call counts per task (for efficiency tracking)
# Updated as we discover the minimal sequences
# ---------------------------------------------------------------------------

OPTIMAL_CALL_COUNTS: dict[str, int] = {
    # Tier 1: simple CRUD (1-2 calls)
    "create_employee": 1,  # POST /employee
    "update_employee": 2,  # GET /employee + PUT /employee/{id}
    "create_customer": 1,  # POST /customer
    "update_customer": 2,  # GET /customer + PUT /customer/{id}
    "create_product": 1,  # POST /product
    "create_department": 1,  # POST /department
    "create_project": 1,  # POST /project
    "enable_module": 2,  # GET /modules + PUT /modules
    "assign_role": 2,  # GET /employee/{id} + PUT /employee/{id}
    # Tier 2: multi-step (1-3 calls)
    "create_order": 2,  # POST /order + POST /order/orderline/list (batch)
    "create_invoice": 3,  # POST /order + POST /order/orderline/list + POST /invoice
    "send_invoice": 1,  # POST /invoice/{id}/:send
    "register_payment": 1,  # POST /invoice/{id}/:payment (1 with direct ID, 2 with search)
    "create_credit_note": 1,  # POST /invoice/{id}/:createCreditNote (1 w/ ID, 2 w/ search)
    "create_travel_expense": 1,  # POST /travelExpense
    "deliver_travel_expense": 1,  # PUT /travelExpense/{id}/:deliver
    "approve_travel_expense": 1,  # PUT /travelExpense/{id}/:approve
    "delete_travel_expense": 2,  # GET /travelExpense + DELETE /travelExpense/{id}
    "link_project_customer": 2,  # GET /project/{id} + PUT /project/{id}
    "create_activity": 1,  # POST /activity
    "update_project": 2,  # GET /project/{id} + PUT /project/{id}
    "create_asset": 1,  # POST /asset
    "update_asset": 2,  # GET /asset/{id} + PUT /asset/{id}
    # Tier 3: complex workflows (1-2 calls)
    "create_voucher": 1,  # POST /ledger/voucher (postings inline)
    "reverse_voucher": 1,  # PUT /ledger/voucher/{id}/:reverse
    "delete_voucher": 2,  # GET /ledger/voucher + DELETE /ledger/voucher/{id}
    "bank_reconciliation": 1,  # POST /bank/reconciliation (+ 1 per adjustment)
    "ledger_correction": 1,  # POST /ledger/voucher (correction postings)
    "year_end_closing": 1,  # POST /ledger/voucher (closing entries)
    "balance_sheet_report": 1,  # GET /balanceSheet
}

# ---------------------------------------------------------------------------
# Server configuration
# ---------------------------------------------------------------------------

# Port for the FastAPI server
SERVER_PORT = 8080

# Host binding
SERVER_HOST = "0.0.0.0"  # noqa: S104  # Bind all interfaces for container deployment

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# Log level
LOG_LEVEL = "INFO"

# Log format
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
