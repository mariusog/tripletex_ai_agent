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

# Default bank account number for ledger account 1920
DEFAULT_BANK_ACCOUNT_NUMBER = "12345678903"

# ---------------------------------------------------------------------------
# LLM configuration
# ---------------------------------------------------------------------------

# Maximum time to wait for LLM response (seconds)
LLM_TIMEOUT = 30

# Number of retries for transient LLM failures
LLM_MAX_RETRIES = 1

# Maximum tokens for LLM response
LLM_MAX_TOKENS = 2048

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
    "update_department",
    "create_project",
    "assign_role",
    "enable_module",
    "delete_customer",
    "delete_product",
    "delete_department",
    "delete_project",
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
    "delete_order",
    "link_project_customer",
    "create_activity",
    "update_project",
    "create_asset",
    "update_asset",
    "create_supplier",
    "delete_supplier",
]

# Tier 3 task types (x3 multiplier, complex workflows, opens Saturday)
TIER_3_TASKS = [
    "create_voucher",
    "reverse_voucher",
    "delete_voucher",
    "run_payroll",
    "create_dimension_voucher",
    "log_timesheet",
    "bank_reconciliation",
    "ledger_correction",
    "year_end_closing",
    "balance_sheet_report",
    "cost_analysis",
]

# All known task types
ALL_TASK_TYPES = TIER_1_TASKS + TIER_2_TASKS + TIER_3_TASKS

# ---------------------------------------------------------------------------
# Optimal WRITE call counts per task (for efficiency tracking)
# IMPORTANT: Only POST, PUT, DELETE, PATCH count toward efficiency.
# GET requests are FREE and do not affect scoring.
# Zero 4xx errors = maximum efficiency bonus.
# ---------------------------------------------------------------------------

OPTIMAL_WRITE_COUNTS: dict[str, int] = {
    # Tier 1: simple CRUD
    "create_employee": 1,  # POST /employee
    "update_employee": 1,  # PUT /employee/{id}
    "create_customer": 1,  # POST /customer
    "update_customer": 1,  # PUT /customer/{id}
    "create_product": 1,  # POST /product
    "create_department": 1,  # POST /department
    "update_department": 1,  # PUT /department/{id}
    "create_project": 1,  # POST /project
    "enable_module": 1,  # PUT /modules
    "assign_role": 1,  # PUT /employee/{id}
    "delete_customer": 1,  # DELETE /customer/{id}
    "delete_product": 1,  # DELETE /product/{id}
    "delete_department": 1,  # DELETE /department/{id}
    "delete_project": 1,  # DELETE /project/{id}
    # Tier 2: multi-step
    "create_order": 2,  # POST /order + POST /order/orderline/list
    "create_invoice": 3,  # POST /order + POST /orderline/list + PUT /order/:invoice
    "send_invoice": 1,  # PUT /invoice/:send (or 4 if creating first)
    "register_payment": 1,  # PUT /invoice/:payment (or 4 if creating first)
    "create_credit_note": 1,  # PUT /invoice/:createCreditNote (or 4 if creating first)
    "create_travel_expense": 1,  # POST /travelExpense (+ 1 per cost)
    "deliver_travel_expense": 1,  # PUT /travelExpense/:deliver
    "approve_travel_expense": 1,  # PUT /travelExpense/:approve
    "delete_travel_expense": 1,  # DELETE /travelExpense/{id}
    "delete_order": 1,  # DELETE /order/{id}
    "link_project_customer": 1,  # PUT /project/{id}
    "create_activity": 1,  # POST /activity
    "update_project": 1,  # PUT /project/{id}
    "create_asset": 1,  # POST /asset
    "update_asset": 1,  # PUT /asset/{id}
    "create_supplier": 1,  # POST /supplier
    "delete_supplier": 1,  # DELETE /supplier/{id}
    # Tier 3: complex workflows
    "create_voucher": 1,  # POST /ledger/voucher
    "reverse_voucher": 1,  # PUT /ledger/voucher/:reverse
    "delete_voucher": 1,  # DELETE /ledger/voucher/{id}
    "run_payroll": 1,  # POST /salary/transaction
    "create_dimension_voucher": 1,  # POST /ledger/voucher (+ dimension setup)
    "log_timesheet": 1,  # POST /timesheet/entry
    "bank_reconciliation": 1,  # POST /bank/reconciliation
    "ledger_correction": 1,  # POST /ledger/voucher
    "year_end_closing": 1,  # POST /ledger/voucher
    "balance_sheet_report": 0,  # GET only — no writes needed
}

# Backward compat alias
OPTIMAL_CALL_COUNTS = OPTIMAL_WRITE_COUNTS

# ---------------------------------------------------------------------------
# Server configuration
# ---------------------------------------------------------------------------

# Port for the FastAPI server
SERVER_PORT = 8080

# Host binding
SERVER_HOST = "0.0.0.0"  # nosec B104  # noqa: S104  # Bind all interfaces for container deployment

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# Log level
LOG_LEVEL = "INFO"

# Log format
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
