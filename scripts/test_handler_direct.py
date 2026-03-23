#!/usr/bin/env python3
"""Test handlers directly against sandbox — no server needed.

This bypasses the LLM classification and calls handlers directly with
known-good params from captured competition runs. Much faster than
going through the full server flow.

Usage:
    export SANDBOX_URL="https://YOUR_SANDBOX.tripletex.dev/v2"
    export SANDBOX_TOKEN="..."

    # Test a specific handler
    python scripts/test_handler_direct.py --task create_customer

    # Test all handlers
    python scripts/test_handler_direct.py --all

    # Test with a specific prompt's params
    python scripts/test_handler_direct.py --task create_invoice --prompt-index 2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from glob import glob
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api_client import TripletexApiError, TripletexClient
from src.handlers import HANDLER_REGISTRY

RUNS_DIR = Path(__file__).parent.parent / "runs"


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
        if not task:
            continue
        # Only include runs that have params
        params = d.get("params") or d.get("params_raw")
        if not params:
            continue
        by_task.setdefault(task, []).append(d)
    return by_task


def test_handler(
    task_type: str,
    params: dict,
    sandbox_url: str,
    sandbox_token: str,
) -> dict:
    """Test a handler directly against the sandbox."""
    handler = HANDLER_REGISTRY.get(task_type)
    if not handler:
        return {"status": "SKIP", "message": f"No handler for {task_type}"}

    client = TripletexClient(base_url=sandbox_url, session_token=sandbox_token)
    try:
        start = time.monotonic()
        result = handler.execute(client, params)
        elapsed = time.monotonic() - start
        return {
            "status": "OK",
            "result": result,
            "api_calls": client.api_call_count,
            "duration": round(elapsed, 2),
        }
    except TripletexApiError as e:
        return {
            "status": "API_ERROR",
            "error": str(e),
            "api_calls": client.api_call_count,
            "validation": [
                {"field": m.get("field"), "message": m.get("message")}
                for m in e.error.validation_messages
            ],
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "error": str(e),
            "api_calls": client.api_call_count,
        }
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test handlers directly against sandbox")
    parser.add_argument("--task", help="Test a specific task type")
    parser.add_argument("--all", action="store_true", help="Test all task types")
    parser.add_argument("--list", action="store_true", help="List available tasks")
    parser.add_argument("--prompt-index", type=int, default=0, help="Which prompt to use (0-based)")
    parser.add_argument("--custom-params", help="JSON string of custom params to test")
    args = parser.parse_args()

    prompts = load_prompts_by_task()

    if args.list:
        print("Available task types:")
        print(f"  {'Task Type':<30} {'Prompts':>7} {'Handler':>8}")
        print(f"  {'-' * 50}")
        for task in sorted(set(list(prompts.keys()) + list(HANDLER_REGISTRY.keys()))):
            n_prompts = len(prompts.get(task, []))
            has_handler = "✅" if task in HANDLER_REGISTRY else "❌"
            print(f"  {task:<30} {n_prompts:>7} {has_handler:>8}")
        return

    sandbox_url = os.environ.get("SANDBOX_URL", "")
    sandbox_token = os.environ.get("SANDBOX_TOKEN", "")
    if not sandbox_url or not sandbox_token:
        print("ERROR: Set SANDBOX_URL and SANDBOX_TOKEN")
        sys.exit(1)

    tasks_to_test = []
    if args.task:
        tasks_to_test = [args.task]
    elif args.all:
        tasks_to_test = sorted(HANDLER_REGISTRY.keys())
    else:
        parser.print_help()
        return

    results = []
    for task in tasks_to_test:
        print(f"\n{'=' * 60}")
        print(f"Testing: {task}")

        if args.custom_params:
            params = json.loads(args.custom_params)
        elif task in prompts:
            idx = min(args.prompt_index, len(prompts[task]) - 1)
            run = prompts[task][idx]
            params = run.get("params", {})
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except json.JSONDecodeError:
                    params = {}
            print(f"  Prompt: {run.get('prompt', '')[:100]}...")
            print(f"  Params: {json.dumps(params, ensure_ascii=False)[:200]}")
        else:
            # Use minimal params
            handler = HANDLER_REGISTRY.get(task)
            if handler:
                required = handler.required_params
                print(f"  No captured prompt. Required params: {required}")
                print("  SKIP: Provide --custom-params or capture a run first")
                results.append({"task": task, "status": "SKIP"})
                continue
            else:
                results.append({"task": task, "status": "NO_HANDLER"})
                continue

        result = test_handler(task, params, sandbox_url, sandbox_token)
        results.append({"task": task, **result})

        status_icon = {"OK": "✅", "API_ERROR": "❌", "ERROR": "💥", "SKIP": "⏭️"}.get(
            result["status"], "?"
        )
        print(f"  {status_icon} {result['status']}: api_calls={result.get('api_calls', '?')}")
        if result.get("result"):
            print(f"  Result: {json.dumps(result['result'], ensure_ascii=False)[:200]}")
        if result.get("error"):
            print(f"  Error: {result['error'][:200]}")
        if result.get("validation"):
            for v in result["validation"]:
                print(f"  ⚠️  {v['field']}: {v['message']}")

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    ok = sum(1 for r in results if r.get("status") == "OK")
    err = sum(1 for r in results if r.get("status") in ("API_ERROR", "ERROR"))
    skip = sum(1 for r in results if r.get("status") == "SKIP")
    print(f"  ✅ {ok} passed  ❌ {err} failed  ⏭️ {skip} skipped")
    for r in results:
        icon = {"OK": "✅", "API_ERROR": "❌", "ERROR": "💥", "SKIP": "⏭️"}.get(
            r.get("status", ""), "?"
        )
        calls = r.get("api_calls", "-")
        print(f"    {icon} {r['task']:<30} calls={calls}")


if __name__ == "__main__":
    main()
