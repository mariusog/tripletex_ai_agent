#!/usr/bin/env python3
"""Summarize all captured competition runs.

Usage:
    python scripts/summarize_runs.py
"""

from __future__ import annotations

import json
from pathlib import Path

RUNS_DIR = Path(__file__).parent.parent / "runs"

# From src/constants.py
OPTIMAL_CALLS = {
    "create_employee": 1, "update_employee": 2, "create_customer": 1,
    "update_customer": 2, "create_product": 1, "create_department": 1,
    "create_project": 1, "enable_module": 2, "assign_role": 2,
    "create_order": 2, "create_invoice": 3, "send_invoice": 1,
    "register_payment": 1, "create_credit_note": 1, "create_travel_expense": 1,
    "deliver_travel_expense": 1, "approve_travel_expense": 1,
    "delete_travel_expense": 2, "link_project_customer": 2,
    "create_activity": 1, "update_project": 2, "create_asset": 1,
    "update_asset": 2, "create_voucher": 1, "reverse_voucher": 1,
    "delete_voucher": 2, "bank_reconciliation": 1, "ledger_correction": 1,
    "year_end_closing": 1, "balance_sheet_report": 1,
}

ALL_TASKS = list(OPTIMAL_CALLS.keys())


def main() -> None:
    runs = []
    for f in sorted(RUNS_DIR.glob("*.json")):
        with open(f) as fh:
            runs.append(json.load(fh))

    if not runs:
        print("No runs found. Run: python scripts/capture_runs.py")
        return

    # Summary table
    print(f"{'='*80}")
    print(f"COMPETITION RUNS SUMMARY — {len(runs)} runs captured")
    print(f"{'='*80}")
    print(f"{'Task Type':<30} {'Calls':>5} {'Opt':>4} {'Δ':>3} {'Errs':>4} {'Time':>6} {'Lang':>4} {'Svc'}")
    print(f"{'-'*80}")

    task_best: dict[str, dict] = {}
    for run in runs:
        task = run.get("task_type", "?")
        calls = run.get("total_api_calls", 0)
        optimal = OPTIMAL_CALLS.get(task, "?")
        delta = calls - optimal if isinstance(optimal, int) else "?"
        errors = len(run.get("errors", []))
        duration = run.get("total_duration_s", 0)
        prompt = run.get("prompt", "")
        service = run.get("service", "?")[-10:]

        # Detect language from prompt
        lang = "?"
        if any(c in prompt for c in "äöüß"): lang = "DE"
        elif any(c in prompt for c in "ñ"): lang = "ES"
        elif any(c in prompt for c in "ção"): lang = "PT"
        elif any(c in prompt for c in "éèêë") and "le" in prompt.lower(): lang = "FR"
        elif "opprett" in prompt.lower() or "registrer" in prompt.lower(): lang = "NO"
        elif "create" in prompt.lower() or "register" in prompt.lower(): lang = "EN"

        status = "ERR" if errors or run.get("status") == "error" else "OK"
        print(
            f"[{status:>3}] {task:<25} {calls:>5} {optimal:>4} {delta:>3} {errors:>4} {duration:>5.1f}s {lang:>4} {service}"
        )

        # Track best per task
        if task not in task_best or calls < task_best[task].get("total_api_calls", 999):
            task_best[task] = run

    # Coverage
    seen = set(task_best.keys())
    missing = set(ALL_TASKS) - seen
    print(f"\n{'='*80}")
    print(f"COVERAGE: {len(seen)}/{len(ALL_TASKS)} task types seen")
    if missing:
        print(f"NEVER SEEN: {', '.join(sorted(missing))}")
    print(f"{'='*80}")

    # Improvement opportunities
    print("\nTOP IMPROVEMENT OPPORTUNITIES (excess API calls):")
    ranked = sorted(task_best.items(), key=lambda x: x[1].get("total_api_calls", 0) - OPTIMAL_CALLS.get(x[0], 0), reverse=True)
    for task, run in ranked[:10]:
        calls = run.get("total_api_calls", 0)
        optimal = OPTIMAL_CALLS.get(task, 0)
        if calls > optimal:
            print(f"  {task}: {calls} calls (optimal {optimal}, {calls - optimal} excess)")


if __name__ == "__main__":
    main()
