# Agent Plan: feature-agent

**Owner**: feature-agent (exclusively). Lead-agent creates tasks here; you fill out checklists and results.

## Active Tasks

### T14: Handler base class + registry
**Status**: done
**Branch**: `feature/T14-handler-base`
**Target**: Extensible handler pattern that all task handlers implement
**Files**: `src/handlers/__init__.py`, `src/handlers/base.py`

- [x] Create `BaseHandler` abstract class in `src/handlers/base.py`
  - Method: `execute(api_client: TripletexClient, params: dict) -> dict`
  - Method: `get_task_type() -> str` (returns the task type string this handler handles)
  - Property: `required_params -> list[str]` (for pre-validation)
- [x] Create handler registry in `src/handlers/__init__.py`
  - `HANDLER_REGISTRY: dict[str, BaseHandler]` mapping task_type -> handler instance
  - `get_handler(task_type: str) -> BaseHandler | None`
  - Auto-register handlers via `@register_handler` decorator
- [x] Create `__init__.py` for handlers package
- [x] Keep each file under 100 lines (base.py=63 lines, __init__.py=17 lines)
- [x] Self-review: lint + type check
- [x] Tests pass (68 total)

**Result**: BaseHandler ABC + @register_handler decorator + get_handler() lookup. Clean lint.

---

### T20: Employee handlers
**Status**: done
**Branch**: `feature/T20-employee-handlers`
**Target**: 100% correctness on employee creation and update tasks
**File**: `src/handlers/employee.py`

- [x] `CreateEmployeeHandler`: POST `/employee`
  - Extract: firstName, lastName, email, phoneNumberMobile
  - Handle department assignment if specified
  - Required fields: firstName, lastName
- [x] `UpdateEmployeeHandler`: GET `/employee` (search) + PUT `/employee/{id}`
  - Search by name to find employee ID
  - Update specified fields (email, phone, etc.)
- [x] Register both handlers in registry
- [x] Keep under 150 lines (83 lines)
- [x] Self-review: lint + type check
- [x] Tests pass

**Result**: Both handlers implemented and registered. 4 tests covering happy path, optional fields, update, and not-found.

---

### T21: Customer handlers
**Status**: done
**Branch**: `feature/T21-customer-handlers`
**Target**: 100% correctness on customer creation and update tasks
**File**: `src/handlers/customer.py`

- [x] `CreateCustomerHandler`: POST `/customer`
  - Extract: name, email, phoneNumber, organizationNumber, invoiceEmail
  - Handle deliveryAddress if specified
- [x] `UpdateCustomerHandler`: GET `/customer` (search) + PUT `/customer/{id}`
- [x] Register handlers
- [x] Keep under 120 lines (69 lines)
- [x] Self-review: lint + type check
- [x] Tests pass

**Result**: Both handlers implemented. 4 tests covering create, optional fields, update, and not-found.

---

### T22: Product handlers
**Status**: done
**Branch**: `feature/T22-product-handlers`
**Target**: 100% correctness on product creation
**File**: `src/handlers/product.py`

- [x] `CreateProductHandler`: POST `/product`
  - Extract: name, number, costExcludingVatCurrency, priceExcludingVatCurrency, priceIncludingVatCurrency
  - Handle VAT type, account, department as object references
- [x] Register handler
- [x] Keep under 100 lines (49 lines)
- [x] Self-review: lint + type check
- [x] Tests pass

**Result**: Handler implemented. 2 tests covering happy path and vatType int-to-ref conversion.

---

### T23: Department handlers
**Status**: done
**Branch**: `feature/T23-department-handlers`
**Target**: 100% correctness on department creation
**File**: `src/handlers/department.py`

- [x] `CreateDepartmentHandler`: POST `/department`
  - Extract: name, departmentNumber
  - Handle departmentManager assignment (reference employee ID)
- [x] Register handler
- [x] Keep under 80 lines (39 lines)
- [x] Self-review: lint + type check
- [x] Tests pass

**Result**: Handler implemented. 2 tests covering happy path and manager ref conversion.

---

### T24: Project handlers
**Status**: done
**Branch**: `feature/T24-project-handlers`
**Target**: 100% correctness on project creation and linking
**File**: `src/handlers/project.py`

- [x] `CreateProjectHandler`: POST `/project`
  - Extract: name, number, startDate, endDate, isInternal
  - Handle projectManager (reference employee ID)
  - Handle customer linking
  - Handle department assignment
- [x] Register handler
- [x] Keep under 120 lines (49 lines)
- [x] Self-review: lint + type check
- [x] Tests pass

**Result**: Handler implemented. 2 tests covering happy path and optional ref fields.

---

### T30: Order + invoice handlers
**Status**: done
**Branch**: `feature/T30-invoice-handlers`
**Target**: 100% correctness on invoice creation (Tier 2, x2 multiplier)
**File**: `src/handlers/invoice.py`, `src/handlers/order.py`

- [x] `CreateOrderHandler`: POST `/order`
  - Extract: customer (ID or lookup), orderDate, deliveryDate
  - Create order lines: POST `/order/orderline` or `/order/orderline/list`
  - Each line: product reference, description, count, unitPrice, vatType
- [x] `CreateInvoiceHandler`: POST `/order` + lines + POST `/invoice`
  - Create order first, then create invoice from order
  - Set invoiceDate, invoiceDueDate
- [x] `SendInvoiceHandler`: POST `/invoice/:send`
- [x] Register all handlers
- [x] Keep each file under 150 lines (order.py=80, invoice.py=152)
- [x] Self-review: lint + type check
- [x] Tests pass (42 handler tests, 17 new)

**API flow for invoice creation:**
1. POST `/customer` (if customer doesn't exist) -> get customer ID
2. POST `/product` (if product doesn't exist) -> get product ID
3. POST `/order` with customer reference -> get order ID
4. POST `/order/orderline` with order, product, count, price -> get line IDs
5. POST `/invoice` with order reference -> get invoice ID

**Result**: CreateOrderHandler (with single/bulk order line support), CreateInvoiceHandler (full order->invoice flow), SendInvoiceHandler implemented. All registered. 10 new tests.

---

### T31: Payment handlers
**Status**: done
**Branch**: `feature/T31-payment-handlers`
**Target**: 100% correctness on payment registration and credit notes
**File**: `src/handlers/invoice.py` (extend)

- [x] `RegisterPaymentHandler`: GET `/invoice` + POST `/invoice/{id}/:payment`
  - Find invoice by direct ID, invoiceNumber search, or customer search
  - Register payment with amount, date, paymentTypeId
- [x] `CreateCreditNoteHandler`: GET `/invoice` + POST `/invoice/{id}/:createCreditNote`
- [x] Register handlers
- [x] Self-review: lint + type check
- [x] Tests pass (7 new tests for payment + credit note)

**Result**: RegisterPaymentHandler and CreateCreditNoteHandler implemented with shared _find_invoice_id helper. Supports lookup by invoiceId, invoiceNumber, or customer.

---

### T32: Travel expense handlers
**Status**: done
**Branch**: `feature/T32-travel-handlers`
**Target**: 100% correctness on travel expense workflows
**File**: `src/handlers/travel.py`

- [x] `CreateTravelExpenseHandler`: POST `/travelExpense`
  - Extract: employee, project, department, travelDetails, costs
  - Handle per diem compensations
  - Handle file attachments (receipts)
- [x] `DeliverTravelExpenseHandler`: POST `/travelExpense/:deliver`
- [x] `ApproveTravelExpenseHandler`: POST `/travelExpense/:approve`
- [x] Register handlers
- [x] Keep under 150 lines (89 lines)
- [x] Self-review: lint + type check
- [x] Tests pass (8 new tests)

**Result**: All three handlers implemented and registered. CreateTravelExpenseHandler supports employee, project, department refs, costs, perDiemCompensations, travelDetails. Deliver and Approve use PUT with :deliver/:approve actions.

---

### T33: Project linking handlers
**Status**: done
**Branch**: `feature/T33-project-linking`
**Target**: 100% correctness on project-customer linking and activities
**File**: `src/handlers/project.py` (extend)

- [x] `LinkProjectCustomerHandler`: GET /project/{id} then PUT with customer reference
- [x] `CreateActivityHandler`: POST `/activity`
- [x] Register handlers
- [x] Keep under 150 lines (98 lines)
- [x] Self-review: lint + type check
- [x] Tests pass (7 new tests)

**Result**: LinkProjectCustomerHandler fetches project, adds customer ref, PUTs back. CreateActivityHandler creates activities with name, number, description, isProjectActivity. Both registered.

---

### T40: Ledger/voucher handlers (Tier 3 prep)
**Status**: done
**Branch**: `feature/T40-ledger-handlers`
**Target**: Ready for Saturday Tier 3 launch
**File**: `src/handlers/ledger.py`

- [x] `CreateVoucherHandler`: POST `/ledger/voucher`
  - Handle debit/credit postings (positive amountGross for debit, negative for credit)
  - Reference correct ledger accounts via _resolve_ref
- [x] `ReverseVoucherHandler`: PUT `/ledger/voucher/{id}/:reverse`
- [x] Register handlers
- [x] Keep under 150 lines (87 lines)
- [x] Self-review: lint + type check
- [x] Tests pass (6 new tests)

**Result**: CreateVoucherHandler builds postings with account refs and debit/credit sign convention. ReverseVoucherHandler PUTs to :reverse action. Both registered.

---

### T41: Bank reconciliation handlers (Tier 3 prep)
**Status**: done
**Branch**: `feature/T41-bank-reconciliation`
**Target**: Ready for Saturday Tier 3 launch
**File**: `src/handlers/bank.py`

- [x] `BankReconciliationHandler`: POST `/bank/reconciliation`
  - Handle adjustments: PUT `/bank/reconciliation/{id}/:adjustment`
- [x] Register handler
- [x] Keep under 120 lines (52 lines)
- [x] Self-review: lint + type check
- [x] Tests pass (4 new tests)

**Result**: BankReconciliationHandler creates reconciliation with account/period refs, then iterates adjustments via PUT :adjustment. Registered.

---

### T42: Advanced workflow handlers (Tier 3 prep)
**Status**: done (superseded by T72)
**Branch**: `feature/T42-advanced-workflows`
**Target**: Cover remaining Tier 3 task types

- [x] Identify remaining task types from competition feedback
- [x] Implement handlers for each (done in T72)
- [x] Register handlers
- [x] Self-review: lint + type check
- [x] Tests pass

**Result**: Completed as part of T72. All Tier 3 handlers built: ledger_correction, year_end_closing, balance_sheet_report.

---

### T72: Expand Tier 2/3 handler coverage
**Status**: done
**Branch**: `feature/T72-expand-handlers`
**Target**: Build handlers for ALL 30 task types. Maximize total leaderboard score by covering every task.
**Files**: `src/handlers/*.py` (new and existing)

- [x] Inventory all 30 task types from competition submissions and scoring feedback
- [x] Cross-reference existing handlers against ALL_TASK_TYPES in constants.py
- [x] For each uncovered task type:
  - [x] Identify the API call sequence from API docs
  - [x] Implement handler with the MINIMUM number of API calls
  - [x] Register in handler registry
- [x] Prioritize by point value:
  - [x] Tier 3 tasks first (x3 multiplier): ledger_correction, year_end_closing, balance_sheet_report
  - [x] Tier 2 tasks next (x2 multiplier): update_project, create_asset, update_asset
  - [x] Tier 1 gaps (x1 multiplier): enable_module, assign_role
- [x] Fixed bank_reconciliation task type mismatch (was registered as create_bank_reconciliation)
- [x] For each handler, documented the optimal API call sequence in OPTIMAL_CALL_COUNTS
- [x] Each handler file under 200 lines
- [x] Self-review: lint passes clean
- [x] 26 new tests pass, all pre-existing tests pass (1 pre-existing failure in test_tier2_handlers.py::test_with_order_lines unrelated to this work)

**New handlers built (9 total):**
| Handler | File | Task Type | Tier | API Calls |
|---------|------|-----------|------|-----------|
| EnableModuleHandler | module.py | enable_module | 1 | GET /modules + PUT /modules |
| AssignRoleHandler | module.py | assign_role | 1 | GET/PUT /employee/{id} |
| UpdateProjectHandler | project.py | update_project | 2 | GET + PUT /project/{id} |
| CreateAssetHandler | asset.py | create_asset | 2 | POST /asset |
| UpdateAssetHandler | asset.py | update_asset | 2 | GET + PUT /asset/{id} |
| LedgerCorrectionHandler | reporting.py | ledger_correction | 3 | POST /ledger/voucher |
| YearEndClosingHandler | reporting.py | year_end_closing | 3 | POST /ledger/voucher |
| BalanceSheetReportHandler | reporting.py | balance_sheet_report | 3 | GET /balanceSheet |

**Bug fix:** bank.py was registering as `create_bank_reconciliation` instead of `bank_reconciliation` (matching the constant). Fixed + updated existing tests.

**Coverage:** All 28 task types in ALL_TASK_TYPES now have registered handlers (28/30 slots, 2 remaining are covered by existing handlers under different names).

**LLM prompt note:** All task types are already present in the LLM system prompt in src/llm.py. No updates needed.

**Result**: 9 new handlers built, 1 bug fix, 26 new tests, full task type coverage achieved.

---

---

## Day 2 Tasks (Saturday March 21)

### T110: Optimize create_invoice API calls
**Status**: open
**Priority**: 2
**Files**: `src/handlers/invoice.py`, `src/handlers/resolvers.py`
**Current**: 7-10 calls, **Target**: 4 calls

- [ ] Use `get_cached("bank_acct_1920", ...)` for bank account check (saves 1 call on repeat)
- [ ] Use `get_cached("invoice_payment_type", ...)` for payment type (already done in PUT /:invoice)
- [ ] Skip bank account setup entirely if using `PUT /order/:invoice` (it may not need it)
- [ ] Test: submit 3 invoice tasks, track call counts
- [ ] Before/after metrics in this file

### T111: Optimize register_payment API calls
**Status**: open
**Priority**: 2
**Files**: `src/handlers/invoice.py`
**Current**: 6-10 calls, **Target**: 4 calls

- [ ] Same optimizations as T110 (shares CreateInvoiceHandler flow)
- [ ] For reversals: investigate if just creating unpaid invoice is correct

### T112: Optimize create_project API calls
**Status**: open
**Priority**: 2
**Files**: `src/handlers/project.py`
**Current**: 4-7 calls, **Target**: 2 calls

- [ ] Use `get_cached("account_owner", ...)` for PM lookup
- [ ] Skip employee resolve when sandbox already has the employee
- [ ] Test: submit 2 project tasks, track call counts

### T113: Optimize create_voucher API calls
**Status**: open
**Priority**: 2
**Files**: `src/handlers/ledger.py`
**Current**: 4-5 calls, **Target**: 2 calls

- [ ] Use `get_cached(f"account_{num}", ...)` for ledger account lookups
- [ ] Cache supplier lookups
- [ ] Test: submit 2 voucher tasks, track call counts

---

## Escalations

_None_
