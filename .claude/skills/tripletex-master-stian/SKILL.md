---
name: tripletex-master-stian
description: "Tripletex API competition expert. ALWAYS use this skill when: fixing handler bugs, improving competition scoring, analyzing run failures, writing or modifying handler code in src/handlers/, working with Tripletex API endpoints, optimizing API call counts, handling Norwegian accounting tasks, classifying multilingual prompts, predicting task types, debugging 422/404/500 errors from Tripletex, working with vouchers/invoices/payments/travel expenses/payroll/ledger corrections, or any task mentioning Tripletex, NM AI, competition, or scoring. This skill contains hard-won knowledge from 196+ real competition runs — use it before writing any handler code."
---

# Tripletex Competition Master Skill

You are an expert at the NM AI Tripletex accounting competition. This skill encodes patterns learned from 196+ real runs across 43+ task types, 7 languages, and 3 scoring tiers. Use it as your primary reference for ALL Tripletex work.

## Architecture Overview

```
src/server.py          → FastAPI entry point
src/task_router.py     → LLM classification → handler dispatch → verification
src/llm.py             → Claude via Vertex AI, dynamic build_system_prompt()
src/api_client.py      → HTTP client with per-session caching
src/verifier.py        → Post-execution verification

src/handlers/           → One handler class per task type
  base.py               → BaseHandler, @register_handler, ParamSpec
  entity_resolver.py    → Unified find-or-create for all entity types
  api_helpers.py        → Shared helpers (bank account, invoice search, travel)
  delete.py             → Generic delete handlers (8 entity types)
  cost_analysis.py      → Expense analysis + project creation

src/services/           → Shared stateless business logic (NO handler-to-handler imports)
  invoice_service.py    → create_full_invoice() — order→lines→invoice→payment
  posting_builder.py    → build_posting(), resolve_account(), merge_vat_postings()
  order_line_builder.py → build_and_post_order_lines() with product resolution
  param_normalizer.py   → Normalize LLM output before handler execution
```

**Key design rule**: Handlers NEVER import other handlers. Shared logic lives in `src/services/` or `src/handlers/entity_resolver.py`.

## Competition Scoring Model

```
score = correctness * tier_multiplier * (1 + efficiency_bonus)
max_per_task = tier_multiplier * 2.0
```

| Tier | Multiplier | Max pts | Task types |
|------|-----------|---------|------------|
| 1 | x1.0 | 2.0 | CRUD: employee, customer, product, department, project, supplier |
| 2 | x2.0 | 4.0 | Invoice, payment, travel, credit note, timesheet, order, asset, send_invoice |
| 3 | x3.0 | 6.0 | Voucher, payroll, dimensions, bank recon, ledger correction, year-end, cost_analysis |

**Efficiency bonus** only unlocks at 100% correctness. Formula: `optimal_calls / actual_calls - error_penalty`. Every 4xx error reduces it. GET requests are FREE for scoring.

**Priority rule**: Fix correctness FIRST (0->1 = biggest gain), then reduce write API calls.

## All 43 Task Types

### Tier 1 — Simple CRUD
`create_employee`, `update_employee`, `create_customer`, `update_customer`, `create_product`, `create_department`, `update_department`, `create_project`, `update_project`, `create_supplier`, `assign_role`, `enable_module`, `create_activity`, `link_project_customer`

### Tier 2 — Multi-step
`create_order`, `create_invoice`, `send_invoice`, `register_payment`, `create_credit_note`, `create_travel_expense`, `deliver_travel_expense`, `approve_travel_expense`, `log_timesheet`, `create_asset`, `update_asset`

### Tier 3 — Complex
`create_voucher`, `reverse_voucher`, `create_dimension_voucher`, `run_payroll`, `bank_reconciliation`, `ledger_correction`, `year_end_closing`, `balance_sheet_report`, `cost_analysis`

### Delete handlers (generic, via delete.py)
`delete_customer`, `delete_product`, `delete_department`, `delete_project`, `delete_order`, `delete_travel_expense`, `delete_supplier`, `delete_voucher`

## The 7 Rules That Matter Most

These come from real failures. Violating any one causes 0 points.

### 1. No global cache — same proxy URL, different sandboxes
The competition reuses the SAME proxy URL but gives a FRESH Tripletex sandbox per submission. Use per-session cache only (`get_cached()` on TripletexClient).

### 2. Payment amount must include VAT
Prompt says "14300 kr eksklusiv MVA" -> invoice total is 17875 (incl 25% VAT). Always GET the invoice and use `amount` or `amountOutstanding` for `paidAmount`.

### 3. Always set bank account before invoicing
`ensure_bank_account()` must run every request. Without it: "bankkontonummer ikke registrert" -> 0 points.

### 4. Avoid 422 errors — they cost efficiency points
Search before POST when entity might exist. Every 422 reduces your efficiency bonus even if the handler recovers.

### 5. Voucher postings must balance to zero
Tripletex requires `sum(amountGross) = 0`. Auto-add balancing entry on account 1920 (bank) if needed.

### 6. Use GROSS amounts for voucher postings
Tripletex auto-decomposes VAT from gross amounts using the account's vatType. Send `amountGross` = total incl MVA. Do NOT manually split VAT — use `merge_vat_postings()` if LLM sent split postings.

### 7. Handlers never import handlers
Shared logic goes in `src/services/` or `entity_resolver.py`. The `create_full_invoice()` service handles the full order->invoice->payment flow.

## Tripletex API Gotchas (learned from 196 runs)

| Gotcha | Tasks affected | Fix |
|--------|---------------|-----|
| `projectRateTypes` is read-only | update_project | Strip from PUT payload |
| `fixedPrice` doesn't exist on project | update_project | Use `isFixedPrice` instead |
| `PUT /:send` not `POST /:send` | send_invoice | Use PUT |
| `PUT /:createCreditNote` not POST | create_credit_note | Use PUT with date as query param |
| `PUT /:payment` uses query params | register_payment | paymentDate, paymentTypeId, paidAmount as params |
| `PUT /order/:invoice` creates invoice | create_invoice | Replaces POST /invoice |
| `department.id` required for employee | create_employee | `ensure_department_exists()` in entity_resolver |
| `dateOfAcquisition` required for asset | create_asset | Default to today |
| Activity must be linked to project | log_timesheet | POST /project/projectActivity after creating |
| Max 24h per timesheet entry | log_timesheet | Split into 7.5h/day entries |
| Supplier ref only on expense accounts | create_voucher | Only add supplier to accounts >= 4000 |
| `postalAddress` must be object | create_supplier | param_normalizer converts string to `{"addressLine1": "..."}` |
| `corrections` vs `postings` format | ledger_correction | `_corrections_to_postings()` flattens nested format |
| Account not found in sandbox | create_voucher | `resolve_account()` auto-creates missing accounts |
| Stale cache after account creation | create_voucher | Fresh GET retry on "already exists" error |
| `postings.customer.id` invalid | create_voucher | Only set customer on receivable accounts 1500-1599 |
| `postings.supplier.id` invalid | ledger_correction | Supplier ref only valid on expense postings |
| `invoiceDateTo` "to and excluding" | register_payment | Extend date range to 2030-01-01 |
| Credit note needs existing invoice | create_credit_note | Search ALL invoices on sandbox before creating new |
| Employee email already exists | create_employee | Catch 422, search by email, patch existing |
| Product number already in use | create_product | Search by number before POST, always create when productNumber specified |
| Missing `remunerationType` on employee | run_payroll | Set remunerationType and division on employee creation |
| Occupation code matching | create_employee | Exact match first, then fuzzy fallback |

## Key Services

### posting_builder.py — Single source of truth for voucher postings
- `resolve_account(api_client, account)` -> `({"id": N}, vat_ref)` — resolves by number, creates if missing, handles name lookup
- `build_posting(api_client, posting, row, supplier)` -> posting payload — handles debit/credit, VAT, department
- `merge_vat_postings(postings, vat_rate)` -> merged postings — collapses manual VAT splits into gross+vatType

### invoice_service.py — Full invoice flow
- `create_full_invoice(api_client, params)` -> InvoiceResult — bank account, customer, project, order, lines, invoice, payment
- Used by: create_invoice, send_invoice, register_payment, create_credit_note

### entity_resolver.py — Find-or-create entities
- `resolve(api_client, entity_type, param)` -> `{"id": N}` — unified for customer, employee, product, supplier
- `ensure_department_exists(api_client)` -> dept ref — creates default department on fresh sandbox
- `_ensure_employee_ready(api_client, emp_id)` — adds dateOfBirth, department, employment if missing

### param_normalizer.py — Pre-handler normalization
- Address string -> object conversion
- Boolean debit/credit normalization
- Nested entity reference flattening

## Dynamic LLM Prompt Generation

`build_system_prompt()` in `src/llm.py` dynamically generates the classification prompt from handler metadata:
- `param_schema` -> parameter documentation per task type
- `disambiguation` -> edge-case classification hints
- `tier` -> grouped by scoring tier
- Includes MULTI-STEP TASKS rules, ACCOUNTING RULES, EFFICIENCY RULES

Handlers define their own metadata — no hardcoded prompt maintenance needed.

## Optimal API Flows

### Tier 1 — Simple CRUD (target: 1-2 calls)
```
create_customer:    POST /customer                              -> 1 call
create_supplier:    POST /supplier                              -> 1 call
create_product:     GET /product?number=X, POST /product        -> 1-2 calls
create_employee:    ensure_dept + POST /employee                -> 1-2 calls
create_department:  POST /department                            -> 1 call
create_project:     resolve PM, POST /project                   -> 2-3 calls
```

### Tier 2 — Multi-step (target: 3-7 calls)
```
create_invoice:     bank + customer + order + lines + PUT /:invoice + payment  -> 5-8
register_payment:   create invoice flow + GET amount + PUT /:payment           -> 6-9
create_credit_note: search invoices + create if needed + PUT /:createCreditNote -> 5-7
log_timesheet:      employee + project + activity + link + POST /entry          -> 5-7
create_travel_expense: employee + POST /travelExpense + costs                  -> 5-8
```

### Tier 3 — Complex (target: 1-5 calls)
```
create_voucher:     resolve accounts + POST /ledger/voucher (sendToLedger)     -> 2-3
ledger_correction:  resolve accounts + POST /ledger/voucher                    -> 2-3
year_end_closing:   GET balanceSheet + closing vouchers                        -> 3-10
run_payroll:        employee + salary type + POST /salary/transaction          -> 3-5
cost_analysis:      GET resultBudget + create projects + activities            -> 5-10
```

## Multilingual Classification

The competition sends prompts in 7 languages. Key translation table:

| Concept | NO | NN | EN | DE | FR | ES | PT |
|---------|-----|-----|-----|-----|-----|-----|-----|
| invoice | faktura | faktura | invoice | Rechnung | facture | factura | fatura |
| payment | betaling | betaling | payment | Zahlung | paiement | pago | pagamento |
| voucher | bilag | bilag | voucher | Beleg | piece comptable | comprobante | comprovante |
| payroll | lonn | lonn | payroll | Gehalt | paie | nomina | salario |
| supplier | leverandor | leverandor | supplier | Lieferant | fournisseur | proveedor | fornecedor |
| employee | ansatt | tilsett | employee | Mitarbeiter | employe | empleado | funcionario |
| department | avdeling | avdeling(ar) | department | Abteilung | departement | departamento | departamento |
| project mgr | prosjektleder | prosjektleiar | project manager | Projektleiter | chef de projet | jefe proyecto | gerente projeto |
| travel exp | reiseregning | reiseregning | travel expense | Reisekosten | frais voyage | gastos viaje | despesa viagem |
| hours | timer | timar | hours | Stunden | heures | horas | horas |
| year-end | arsoppgjor | arsoppgjer | year-end | Jahresabschluss | cloture | cierre | encerramento |
| correction | korreksjon | korreksjon | correction | Korrektur | correction | correccion | correcao |
| cost analysis | kostnadsanalyse | kostnadsanalyse | cost analysis | Kostenanalyse | analyse couts | analisis costos | analise custos |

**Nynorsk special**: "opprett ein"="opprett en", "knytt til"="knyttet til", "heiter"="heter", "tilsett"="ansatt", "fodd"="fodt"

## Error Pattern Reference

From 196 runs — actual errors and their fixes:

| Error pattern | Count | Root cause | Fix |
|--------------|-------|------------|-----|
| `email: allerede en bruker` | 11 | Employee email exists | Catch 422, search by email, patch |
| `number: i bruk` | 7 | Product/dept number duplicate | Search by number before POST |
| `department.id: fylles ut` | 5 | Employee needs department | `ensure_department_exists()` |
| `bankkontonummer ikke registrert` | 4 | Bank account not set | `ensure_bank_account()` every time |
| `Internt felt (account)` | 3 | Account doesn't exist in sandbox | `resolve_account()` auto-creates |
| `postings: Kan ikke vaere null` | 3 | corrections[] not flattened | `_corrections_to_postings()` |
| `postings.customer.id` invalid | 2 | Customer ref on wrong account | Only on 1500-1599 receivables |
| `postings.supplier.id: Leverandor mangler` | 2 | Supplier ref on wrong account | Only on accounts >= 4000 |
| `405 Method Not Allowed` | 2 | POST instead of PUT | Use PUT for /:send, /:createCreditNote |
| `projectManager.id: ikke tilgang` | 2 | PM not authorized | Use account owner as PM, create requested PM separately |
| `fixedPrice: eksisterer ikke` | 1 | Wrong field name | Use `isFixedPrice` |
| `projectChargeableHours > 24` | 1 | Too many hours per day | Split into 7.5h entries |
| `aktiviteten kan ikke benyttes` | 1 | Activity not linked to project | POST /project/projectActivity |
| `employments.employmentDetails` | 1 | Employment detail format wrong | Check required employment fields |

## Accounting Rules (encoded in LLM prompt)

- **Depreciation**: debit 6010/6020/6030 (expense), credit 1209/1249/1259 (accumulated). NEVER credit 1700.
- **Prepaid expense**: debit operating expense (6300 rent, etc.), credit 1700/1720. NEVER use 6010.
- **Salary accrual**: debit 5000 (salary), credit 2900 (accrued). Amount inferred from balance sheet if 0.
- **Tax provision**: 22% of taxable profit. `_fix_tax_amounts()` computes from actual P&L.
- **Exchange rate**: 8060 AGIO (gain), 8160 DISAGIO (loss).
- **VAT rates**: 25% standard, 15% food/beverage, 12% transport, 0% exempt.
- **Year-end closing**: close revenue/expense to 8800 equity. Exclude tax accounts.
- **Expense analysis**: top 3 accounts with biggest increase (not top 5).

## Task Type Decision Tree

```
Prompt mentions hours/timer/Stunden + project -> log_timesheet
Prompt mentions salary/lonn/Gehalt/nomina -> run_payroll
Prompt mentions supplier invoice/leverandorfaktura -> create_voucher
Prompt mentions custom dimension + voucher -> create_dimension_voucher
Prompt mentions "create and send" invoice -> create_invoice (with send_invoice=true)
Prompt mentions payment reversal/stornering -> register_payment (reversal=true)
Prompt mentions credit note/kreditnota -> create_credit_note
Prompt mentions year-end/arsoppgjor/cloture annuelle -> year_end_closing
Prompt mentions ledger errors/corrections -> ledger_correction
Prompt mentions bank reconciliation -> bank_reconciliation
Prompt mentions cost/expense analysis + create projects -> cost_analysis
Prompt mentions multiple departments -> create_department (items=[])
Prompt mentions project lifecycle (hours+costs+invoice) -> DECOMPOSE into multiple tasks
Prompt mentions attach PDF -> read PDF, classify from content
Prompt mentions overdue invoice + fee -> create_voucher (late fee posting)
```

## Handler Checklist (before writing/modifying any handler)

1. Does it handle missing params gracefully (no KeyError)?
2. Does it set required fields with defaults (date=today, department=first)?
3. Does it avoid 422 by searching before creating?
4. Does it use `get_cached()` for repeated lookups within a request?
5. Does it strip read-only fields from PUT payloads?
6. Does it auto-balance voucher postings?
7. Does it work for all 7 languages?
8. Does it handle both dict and string params for entities?
9. Does it use actual invoice `amount` for payments (not prompt amount)?
10. Does `ensure_bank_account()` run before invoice creation?
11. Does it use `entity_resolver.resolve()` for entity find-or-create?
12. Does it use `build_posting()` from `posting_builder.py` (not inline)?
13. Does it have `param_schema` and `disambiguation` metadata?

## File Reference

| File | Purpose |
|------|---------|
| `src/handlers/*.py` | Task handlers — one per task type |
| `src/handlers/entity_resolver.py` | Unified find-or-create for all entities |
| `src/handlers/api_helpers.py` | Shared helpers (bank, invoice search, travel) |
| `src/handlers/delete.py` | Generic delete handlers (8 entities) |
| `src/services/invoice_service.py` | Full invoice flow (order->lines->invoice->payment) |
| `src/services/posting_builder.py` | Voucher posting construction + account resolution |
| `src/services/order_line_builder.py` | Order line building + product resolution |
| `src/services/param_normalizer.py` | LLM output normalization |
| `src/llm.py` | Dynamic LLM prompt + classification |
| `src/constants.py` | Task types, tiers, optimal call counts |
| `src/task_router.py` | Routes classification -> handler, retry logic |
| `src/api_client.py` | HTTP client with per-session caching |
| `src/verifier.py` | Post-execution verification logging |
| `runs/*.json` | Competition run logs (196+) |
| `scripts/capture_runs.py` | Capture from Cloud Run logs |
| `scripts/summarize_runs.py` | Summarize run performance |
| `scripts/auto-improve-stian.sh` | Capture + analyze cycle |

## Workflow: Fix a Failing Task

1. Read the run JSON: `cat runs/<file>.json`
2. Check `error_details` for the Tripletex error message
3. Look up the error in the table above
4. Read the handler: `cat src/handlers/<module>.py`
5. Check if the service layer handles it: `cat src/services/<service>.py`
6. Apply the known fix pattern
7. Run tests: `python -m pytest tests/ -q --tb=short -m "not slow" 2>&1 | tail -20`
8. Capture new runs: `bash scripts/auto-improve-stian.sh`
9. Verify improvement in new run data

## Multi-Step Task Decomposition

The LLM can return multiple tasks in the `tasks` array. Common patterns:

| Prompt pattern | Decomposition |
|---------------|--------------|
| Book fee + invoice + send | create_voucher, create_invoice, send_invoice |
| Create invoice + register payment | create_invoice (with register_payment in params) |
| Project lifecycle (hours + costs + invoice) | create_project, log_timesheet, create_voucher, create_invoice |
| Create employee + assign role | create_employee, assign_role |
| Find overdue invoice + partial payment | register_payment (searches automatically) |
