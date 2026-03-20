#!/usr/bin/env python3
"""Export a handler's source code alongside its run results.

Creates a shareable bundle: handler code + run JSON + score.
Teammates can compare approaches for the same task type.

Usage:
    python scripts/export_handler.py create_invoice
    python scripts/export_handler.py --all
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

HANDLERS_DIR = Path("src/handlers")
RUNS_DIR = Path("runs")
EXPORT_DIR = Path("runs/handler_snapshots")

# Map task types to their handler files
TASK_TO_FILE = {
    "create_employee": "employee.py", "update_employee": "employee.py",
    "create_customer": "customer.py", "update_customer": "customer.py",
    "create_supplier": "customer.py",
    "create_product": "product.py",
    "create_department": "department.py",
    "create_project": "project.py", "update_project": "project.py",
    "link_project_customer": "project.py", "create_activity": "project.py",
    "create_order": "order.py",
    "create_invoice": "invoice.py", "send_invoice": "invoice.py",
    "register_payment": "invoice.py", "create_credit_note": "invoice.py",
    "create_travel_expense": "travel.py", "delete_travel_expense": "travel.py",
    "deliver_travel_expense": "travel.py", "approve_travel_expense": "travel.py",
    "create_voucher": "ledger.py", "delete_voucher": "ledger.py",
    "reverse_voucher": "ledger.py",
    "bank_reconciliation": "bank.py",
    "ledger_correction": "reporting.py", "year_end_closing": "reporting.py",
    "balance_sheet_report": "reporting.py",
    "create_asset": "asset.py", "update_asset": "asset.py",
    "assign_role": "module.py", "enable_module": "module.py",
}


def export_task(task_type: str) -> None:
    """Export handler + runs for a task type."""
    handler_file = TASK_TO_FILE.get(task_type)
    if not handler_file:
        print(f"Unknown task type: {task_type}")
        return

    task_dir = EXPORT_DIR / task_type
    task_dir.mkdir(parents=True, exist_ok=True)

    # Copy handler source
    src = HANDLERS_DIR / handler_file
    if src.exists():
        shutil.copy2(src, task_dir / handler_file)
        print(f"  Handler: {handler_file}")

    # Copy matching runs
    run_count = 0
    for run_file in sorted(RUNS_DIR.glob("*.json")):
        with open(run_file) as f:
            try:
                run = json.load(f)
            except json.JSONDecodeError:
                continue
        if run.get("task_type") == task_type:
            shutil.copy2(run_file, task_dir / run_file.name)
            run_count += 1

    print(f"  Runs: {run_count} files")
    print(f"  Exported to: {task_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_type", nargs="?", help="Task type to export")
    parser.add_argument("--all", action="store_true", help="Export all task types")
    args = parser.parse_args()

    if args.all:
        seen = set()
        for f in RUNS_DIR.glob("*.json"):
            with open(f) as fh:
                try:
                    run = json.load(fh)
                except json.JSONDecodeError:
                    continue
                task = run.get("task_type")
                if task and task not in seen:
                    seen.add(task)
                    print(f"\n=== {task} ===")
                    export_task(task)
    elif args.task_type:
        export_task(args.task_type)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
