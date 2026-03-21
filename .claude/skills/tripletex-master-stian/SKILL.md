---
name: tripletex-master-stian
description: "Tripletex API competition expert. ALWAYS use this skill when: fixing handler bugs, improving competition scoring, analyzing run failures, writing or modifying handler code in src/handlers/, working with Tripletex API endpoints, optimizing API call counts, handling Norwegian accounting tasks, classifying multilingual prompts, predicting task types, debugging 422/404/500 errors from Tripletex, working with vouchers/invoices/payments/travel expenses/payroll/ledger corrections, or any task mentioning Tripletex, NM AI, competition, or scoring. This skill contains hard-won knowledge from 113+ real competition runs — use it before writing any handler code."
---

# Tripletex Competition Master Skill

You are an expert at the NM AI Tripletex accounting competition. This skill encodes patterns learned from 113+ real runs across 41 task types, 7 languages, and 3 scoring tiers. Use it as your primary reference for ALL Tripletex work.

## Competition Scoring Model

```
score = correctness × tier_multiplier × (1 + efficiency_bonus)
max_per_task = tier_multiplier × 2.0
```

| Tier | Multiplier | Max pts | Task types |
|------|-----------|---------|------------|
| 1 | ×1.0 | 2.0 | CRUD: employee, customer, product, department, project, supplier |
| 2 | ×2.0 | 4.0 | Invoice, payment, travel, credit note, timesheet, order, asset |
| 3 | ×3.0 | 6.0 | Voucher, payroll, dimensions, bank recon, ledger correction, year-end |

**Efficiency bonus** only unlocks at 100% correctness. Formula: `optimal_calls / actual_calls - error_penalty`. Every 4xx error reduces it. Fewer API calls = higher bonus.

**Priority rule**: Fix correctness FIRST (0→1 = biggest gain), then reduce API calls.

## The 5 Rules That Matter Most

These come from real failures. Violating any one causes 0 points.

### 1. No global cache — same proxy URL, different sandboxes
The competition reuses the SAME proxy URL but gives a FRESH Tripletex sandbox per submission. Global cache (keyed by base_url) returns stale data. Use per-session cache only (`self._cache` on TripletexClient, not `_global_cache`).

### 2. Payment amount must include VAT
Prompt says "14300 kr eksklusiv MVA" → invoice total is 17875 (incl 25% VAT). If you pay 14300, `isPaid=False` → 0 points. Always GET the invoice first and use `amountOutstanding` for `paidAmount`.

### 3. Always set bank account before invoicing
`_ensure_bank_account()` must run every request (not cached). Without it: "Faktura kan ikke opprettes før selskapet har registrert et bankkontonummer" → 0 points.

### 4. Avoid 422 errors — they cost efficiency points
Search before POST when entity might exist. Search product by number before creating. Catch employee email duplicates. Every 422 reduces your efficiency bonus even if the handler recovers.

### 5. Voucher postings must balance to zero
Tripletex requires `sum(amountGross) = 0`. If LLM sends only debit postings, auto-add a balancing credit entry on account 1920 (bank). But DON'T double-balance when both debit and credit are already present.

## Tripletex API Gotchas (learned from failures)

| Gotcha | Tasks affected | Fix |
|--------|---------------|-----|
| `projectRateTypes` is read-only | update_project | Strip from PUT payload |
| `fixedPrice` doesn't exist on project | update_project | Don't send it |
| `PUT /:send` not `POST /:send` | send_invoice | Use PUT |
| `PUT /:createCreditNote` not POST | create_credit_note | Use PUT with date as query param |
| `PUT /:payment` uses query params | register_payment | paymentDate, paymentTypeId, paidAmount as params |
| `PUT /order/:invoice` creates invoice | create_invoice | Replaces POST /invoice |
| `department.id` required for employee | create_employee | Fetch first department as default |
| `dateOfAcquisition` required for asset | create_asset | Default to today |
| Activity must be linked to project | log_timesheet | POST /project/projectActivity after creating |
| Max 24h per timesheet entry | log_timesheet | Split into 7.5h/day entries |
| Supplier ref only on expense accounts | create_voucher | Only add supplier to accounts ≥ 4000 |
| `postalAddress` must be object, not string | create_supplier | Convert string to `{"addressLine1": "..."}` |
| `corrections` vs `postings` format | ledger_correction | Flatten corrections[].postings into flat list |
| `debitAmount`/`creditAmount` keys | ledger_correction | Normalize to `debit`/`credit` |

## Optimal API Flows

### Tier 1 — Simple CRUD (target: 1 call)
```
create_customer:  POST /customer                           → 1 call
create_supplier:  POST /supplier                           → 1 call
create_product:   GET /product?number=X, POST /product     → 1-2 calls
create_employee:  GET /department(cached), POST /employee  → 1-2 calls
create_department: POST /department                        → 1 call
create_project:   resolve PM, POST /project                → 2-3 calls
```

### Tier 2 — Multi-step (target: 3-7 calls)
```
create_invoice:   bank_acct + customer + order + lines + PUT /order/:invoice + payment → 5-8
register_payment: create invoice flow + GET invoice amount + PUT /:payment             → 6-9
create_travel_expense: employee + POST /travelExpense + costs + perDiem               → 5-8
log_timesheet:    employee + project + activity + link + POST /timesheet/entry         → 5-7
```

### Tier 3 — Complex (target: 1-5 calls)
```
create_voucher:   bulk resolve accounts + POST /ledger/voucher    → 2-3
ledger_correction: bulk resolve + POST /ledger/voucher            → 2-3
year_end_closing:  balance sheet + closing vouchers               → 3-10
run_payroll:       employee + salary type + POST /salary/transaction → 3-5
```

## Multilingual Classification

The competition sends prompts in 7 languages. Key translation table:

| Concept | NO | NN | EN | DE | FR | ES | PT |
|---------|-----|-----|-----|-----|-----|-----|-----|
| invoice | faktura | faktura | invoice | Rechnung | facture | factura | fatura |
| payment | betaling | betaling | payment | Zahlung | paiement | pago | pagamento |
| voucher | bilag | bilag | voucher | Beleg | pièce | comprobante | comprovante |
| payroll | lønn | lønn | payroll | Gehalt | paie | nómina | salário |
| supplier | leverandør | leverandør | supplier | Lieferant | fournisseur | proveedor | fornecedor |
| employee | ansatt | tilsett | employee | Mitarbeiter | employé | empleado | funcionário |
| department | avdeling | avdeling(ar) | department | Abteilung | département | departamento | departamento |
| project mgr | prosjektleder | prosjektleiar | project manager | Projektleiter | chef de projet | jefe proyecto | gerente projeto |
| travel exp | reiseregning | reiseregning | travel expense | Reisekosten | frais voyage | gastos viaje | despesa viagem |
| hours | timer | timar | hours | Stunden | heures | horas | horas |
| year-end | årsoppgjør | årsoppgjer | year-end | Jahresabschluss | clôture | cierre | encerramento |
| correction | korreksjon | korreksjon | correction | Korrektur | correction | corrección | correção |

**Nynorsk special**: "opprett ein"="opprett en", "knytt til"="knyttet til", "heiter"="heter", "tilsett"="ansatt", "fødd"="født"

## Error Pattern Reference

From 113 runs — these are the actual errors and their fixes:

| Error pattern | Count | Root cause | Fix |
|--------------|-------|------------|-----|
| `email: allerede en bruker` | 11 | Employee with email exists | Catch 422, search by email |
| `number: i bruk` | 7 | Product/dept number duplicate | Search by number before POST |
| `department.id: fylles ut` | 5 | Employee needs department | GET first department as default |
| `bankkontonummer ikke registrert` | 4 | Bank account not set | Run _ensure_bank_account every time |
| `405 Method Not Allowed` | 2 | POST instead of PUT | Use PUT for /:send, /:createCreditNote |
| `fixedPrice: eksisterer ikke` | 1 | Read-only field in PUT | Strip from payload |
| `projectChargeableHours > 24` | 1 | Too many hours per day | Split into 7.5h entries |
| `aktiviteten kan ikke benyttes` | 1 | Activity not linked to project | POST /project/projectActivity |
| `postings: null` | 1 | corrections[] not flattened | Flatten nested postings |
| `supplier.id: Leverandør mangler` | 1 | Supplier ref on wrong account | Only on accounts ≥ 4000 |

## Handler Checklist (before writing/modifying any handler)

1. Does it handle missing params gracefully (no KeyError)?
2. Does it set required fields with defaults (date=today, department=first)?
3. Does it avoid 422 by searching before creating?
4. Does it use `get_cached()` for repeated lookups within a request?
5. Does it strip read-only fields from PUT payloads?
6. Does it auto-balance voucher postings?
7. Does it work for all 7 languages?
8. Does it handle both dict and string params for entities?
9. Does it use `amountOutstanding` for payments (not prompt amount)?
10. Does `_ensure_bank_account()` run before invoice creation?

## Task Type Decision Tree

```
Prompt mentions hours/timer/Stunden + project → log_timesheet
Prompt mentions salary/lønn/Gehalt/nómina → run_payroll
Prompt mentions supplier invoice/leverandørfaktura → create_voucher
Prompt mentions custom dimension + voucher → create_dimension_voucher
Prompt mentions "create and send" invoice → create_invoice (with send_invoice=true)
Prompt mentions payment reversal/stornering → register_payment (reversal=true)
Prompt mentions credit note/kreditnota → create_credit_note
Prompt mentions year-end/årsoppgjør → year_end_closing
Prompt mentions ledger errors/corrections → ledger_correction
Prompt mentions bank reconciliation → bank_reconciliation
Prompt mentions multiple departments → create_department (items=[])
Prompt mentions attach PDF → read PDF, classify from content
```

## File Reference

| File | Purpose |
|------|---------|
| `src/handlers/*.py` | Task handlers — one per task type |
| `src/llm.py` | LLM prompt and classification |
| `src/constants.py` | Task types, tiers, optimal call counts |
| `src/task_router.py` | Routes classification → handler |
| `src/api_client.py` | HTTP client with caching |
| `src/verifier.py` | Post-execution verification |
| `runs/*.json` | Competition run logs |
| `scripts/capture_runs.py` | Capture from Cloud Run logs |
| `scripts/summarize_runs.py` | Summarize run performance |

## Workflow: Fix a Failing Task

1. Read the run JSON: `cat runs/<file>.json`
2. Check `error_details` for the Tripletex error message
3. Look up the error in the table above
4. Read the handler: `cat src/handlers/<module>.py`
5. Apply the known fix pattern
6. Run tests: `python -m pytest tests/ -q --tb=short -m "not slow"`
7. Deploy: `./deploy-stian.sh` or `bash /tmp/deploy-to.sh <service>`
8. Wait for next run and verify improvement
