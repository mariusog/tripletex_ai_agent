#!/usr/bin/env python3
"""Competition test harness — replay real prompts and verify results.

Usage:
    # Test against local server with sandbox credentials
    python scripts/competition_test.py --task create_customer

    # Test against deployed server
    python scripts/competition_test.py --task create_invoice --server https://tripletex-agent-2-...run.app

    # Test all task types
    python scripts/competition_test.py --all

    # List available prompts
    python scripts/competition_test.py --list

Requires sandbox credentials:
    export SANDBOX_URL="https://YOUR_SANDBOX.tripletex.dev/v2"
    export SANDBOX_TOKEN="..."
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from glob import glob
from pathlib import Path

import httpx

RUNS_DIR = Path(__file__).parent.parent / "runs"
DEFAULT_SERVER = "http://localhost:8080"


def load_prompts_by_task() -> dict[str, list[dict]]:
    """Load all captured run prompts grouped by task type."""
    by_task: dict[str, list[dict]] = {}
    for f in sorted(glob(str(RUNS_DIR / "*.json"))):
        try:
            with open(f) as fh:
                d = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        task = d.get("task_type", "")
        prompt = d.get("prompt", "")
        if not task or not prompt:
            continue
        by_task.setdefault(task, []).append(d)
    return by_task


def call_solve(server: str, prompt: str, sandbox_url: str, sandbox_token: str) -> dict:
    """Call POST /solve on our server."""
    body = {
        "prompt": prompt,
        "tripletex_credentials": {
            "base_url": sandbox_url,
            "session_token": sandbox_token,
        },
    }
    try:
        resp = httpx.post(
            f"{server}/solve",
            json=body,
            timeout=120,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def verify_customer(api: httpx.Client, params: dict) -> list[str]:
    """Verify customer was created correctly."""
    checks = []
    name = params.get("name", "")
    if not name:
        cust = params.get("customer", {})
        name = cust.get("name", "") if isinstance(cust, dict) else str(cust)

    resp = api.get("/customer", params={"name": name, "count": 5, "fields": "*"})
    values = resp.json().get("values", [])

    # Find exact match
    found = None
    for v in values:
        if v.get("name", "").strip().lower() == name.strip().lower():
            found = v
            break

    if not found:
        checks.append(f"FAIL: Customer '{name}' not found")
        return checks
    checks.append(f"PASS: Customer '{name}' exists (id={found['id']})")

    org = params.get("organizationNumber", "")
    if not org:
        cust = params.get("customer", {})
        org = cust.get("organizationNumber", "") if isinstance(cust, dict) else ""
    if org and str(found.get("organizationNumber", "")) != str(org):
        actual_org = found.get("organizationNumber")
        checks.append(f"FAIL: orgNr expected={org} got={actual_org}")
    elif org:
        checks.append(f"PASS: organizationNumber={org}")

    email = params.get("email", "")
    if email and found.get("email") != email:
        checks.append(f"FAIL: email expected={email} got={found.get('email')}")
    elif email:
        checks.append(f"PASS: email={email}")

    return checks


def verify_supplier(api: httpx.Client, params: dict) -> list[str]:
    """Verify supplier was created correctly."""
    checks = []
    name = params.get("name", "")
    resp = api.get("/supplier", params={"name": name, "count": 5, "fields": "*"})
    values = resp.json().get("values", [])

    found = None
    for v in values:
        if v.get("name", "").strip().lower() == name.strip().lower():
            found = v
            break

    if not found:
        checks.append(f"FAIL: Supplier '{name}' not found")
        return checks
    checks.append(f"PASS: Supplier '{name}' exists (id={found['id']})")

    org = params.get("organizationNumber", "")
    if org and str(found.get("organizationNumber", "")) != str(org):
        actual_org = found.get("organizationNumber")
        checks.append(f"FAIL: orgNr expected={org} got={actual_org}")
    elif org:
        checks.append(f"PASS: organizationNumber={org}")

    return checks


def verify_employee(api: httpx.Client, params: dict) -> list[str]:
    """Verify employee was created correctly."""
    checks = []
    first = params.get("firstName", "")
    last = params.get("lastName", "")

    resp = api.get(
        "/employee",
        params={"firstName": first, "lastName": last, "count": 5, "fields": "*"},
    )
    values = resp.json().get("values", [])

    found = None
    for v in values:
        if (
            v.get("firstName", "").lower() == first.lower()
            and v.get("lastName", "").lower() == last.lower()
        ):
            found = v
            break

    if not found:
        checks.append(f"FAIL: Employee '{first} {last}' not found")
        return checks
    checks.append(f"PASS: Employee '{first} {last}' exists (id={found['id']})")

    if params.get("email") and found.get("email") != params["email"]:
        checks.append(f"FAIL: email expected={params['email']} got={found.get('email')}")
    elif params.get("email"):
        checks.append(f"PASS: email={params['email']}")

    if params.get("dateOfBirth"):
        dob = found.get("dateOfBirth", "")
        if dob and params["dateOfBirth"] not in dob:
            checks.append(f"FAIL: dateOfBirth expected={params['dateOfBirth']} got={dob}")
        elif dob:
            checks.append(f"PASS: dateOfBirth={dob}")

    return checks


def verify_product(api: httpx.Client, params: dict) -> list[str]:
    """Verify product was created correctly."""
    checks = []
    name = params.get("name", "")
    number = params.get("number")

    if number:
        resp = api.get("/product", params={"number": str(number), "count": 1, "fields": "*"})
    else:
        resp = api.get("/product", params={"name": name, "count": 5, "fields": "*"})
    values = resp.json().get("values", [])

    found = None
    if number:
        found = values[0] if values else None
    else:
        for v in values:
            if v.get("name", "").strip().lower() == name.strip().lower():
                found = v
                break

    if not found:
        checks.append(f"FAIL: Product '{name}' (number={number}) not found")
        return checks
    checks.append(f"PASS: Product exists (id={found['id']}, name={found.get('name')})")

    if name and found.get("name", "").lower() != name.lower():
        checks.append(f"FAIL: name expected={name} got={found.get('name')}")

    price = params.get("priceExcludingVatCurrency")
    if price and found.get("priceExcludingVatCurrency") != price:
        checks.append(f"WARN: price expected={price} got={found.get('priceExcludingVatCurrency')}")

    return checks


def verify_department(api: httpx.Client, params: dict) -> list[str]:
    """Verify department(s) were created."""
    checks = []
    items = params.get("items", [])
    names = [i["name"] for i in items] if items else [params.get("name", "")]

    for name in names:
        resp = api.get("/department", params={"name": name, "count": 5, "fields": "id,name"})
        values = resp.json().get("values", [])
        found = any(v.get("name", "").strip().lower() == name.strip().lower() for v in values)
        if found:
            checks.append(f"PASS: Department '{name}' exists")
        else:
            checks.append(f"FAIL: Department '{name}' not found")

    return checks


def verify_invoice(api: httpx.Client, params: dict) -> list[str]:
    """Verify invoice was created."""
    checks = []
    resp = api.get("/invoice", params={"count": 5, "fields": "*"})
    invoices = resp.json().get("values", [])

    if not invoices:
        checks.append("FAIL: No invoices found")
        return checks
    checks.append(f"PASS: Invoice exists (id={invoices[0]['id']})")

    inv = invoices[0]
    if inv.get("amount"):
        checks.append(f"INFO: Invoice amount={inv['amount']}")

    # Check if payment registered
    payment = params.get("register_payment") or params.get("payment")
    if payment:
        if inv.get("amountOutstanding", 0) == 0:
            checks.append("PASS: Invoice fully paid")
        else:
            checks.append(
                f"WARN: Invoice outstanding={inv.get('amountOutstanding')} (may need payment)"
            )

    return checks


VERIFIERS = {
    "create_customer": verify_customer,
    "create_supplier": verify_supplier,
    "create_employee": verify_employee,
    "create_product": verify_product,
    "create_department": verify_department,
    "create_invoice": verify_invoice,
    "register_payment": verify_invoice,
}


def run_test(server: str, sandbox_url: str, sandbox_token: str, run_data: dict) -> dict:
    """Run a single test: call solve, then verify."""
    task = run_data.get("task_type", "?")
    prompt = run_data["prompt"]
    params = run_data.get("params", {})

    print(f"\n{'=' * 70}")
    print(f"TASK: {task}")
    print(f"PROMPT: {prompt[:120]}...")

    # Call our server
    start = time.monotonic()
    result = call_solve(server, prompt, sandbox_url, sandbox_token)
    elapsed = time.monotonic() - start
    print(f"SOLVE: {result.get('status', 'error')} ({elapsed:.1f}s)")

    # Verify in sandbox
    verifier = VERIFIERS.get(task)
    checks = []
    if verifier:
        api = httpx.Client(
            base_url=sandbox_url,
            auth=("0", sandbox_token),
            timeout=30,
        )
        try:
            checks = verifier(api, params)
        except Exception as e:
            checks = [f"ERROR: Verification failed: {e}"]
        finally:
            api.close()
    else:
        checks = [f"SKIP: No verifier for task type '{task}'"]

    for check in checks:
        status = check.split(":")[0]
        color = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "SKIP": "⏭️", "INFO": "i"}.get(
            status, "  "
        )
        print(f"  {color} {check}")

    passed = sum(1 for c in checks if c.startswith("PASS"))
    failed = sum(1 for c in checks if c.startswith("FAIL"))
    return {"task": task, "passed": passed, "failed": failed, "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description="Competition test harness")
    parser.add_argument("--task", help="Test a specific task type")
    parser.add_argument("--all", action="store_true", help="Test all task types")
    parser.add_argument("--list", action="store_true", help="List available prompts")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="Server URL")
    parser.add_argument("--limit", type=int, default=1, help="Max prompts per task type")
    args = parser.parse_args()

    prompts = load_prompts_by_task()

    if args.list:
        print("Available task types with captured prompts:")
        for task, runs in sorted(prompts.items()):
            print(f"  {task:<30} {len(runs):>3} prompts")
        return

    sandbox_url = os.environ.get("SANDBOX_URL", "")
    sandbox_token = os.environ.get("SANDBOX_TOKEN", "")
    if not sandbox_url or not sandbox_token:
        print("ERROR: Set SANDBOX_URL and SANDBOX_TOKEN environment variables")
        print("  export SANDBOX_URL='https://YOUR_SANDBOX.tripletex.dev/v2'")
        print("  export SANDBOX_TOKEN='...'")
        sys.exit(1)

    tasks_to_test = []
    if args.task:
        if args.task not in prompts:
            print(f"No prompts for task type '{args.task}'")
            sys.exit(1)
        tasks_to_test = [args.task]
    elif args.all:
        tasks_to_test = sorted(prompts.keys())
    else:
        parser.print_help()
        return

    results = []
    for task in tasks_to_test:
        runs = prompts[task][: args.limit]
        for run in runs:
            result = run_test(args.server, sandbox_url, sandbox_token, run)
            results.append(result)

    # Summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    for r in results:
        status = "✅" if r["failed"] == 0 else "❌"
        print(f"  {status} {r['task']:<30} {r['passed']} passed, {r['failed']} failed")
    print(f"\nTotal: {total_passed} passed, {total_failed} failed")


if __name__ == "__main__":
    main()
