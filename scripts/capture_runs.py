#!/usr/bin/env python3
"""Capture competition runs from Cloud Run logs into shared JSON files.

Usage:
    python scripts/capture_runs.py [--service SERVICE_NAME] [--limit N]

Each run is saved to runs/YYYY-MM-DD_HH-MM-SS_{task_type}.json
Existing runs are skipped (idempotent).

Teammates can run this against their own service to contribute runs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

RUNS_DIR = Path(__file__).parent.parent / "runs"
PROJECT_ID = "YOUR_GCP_PROJECT_ID"
REGION = "europe-west1"


def refresh_token() -> None:
    """Refresh GCP access token from ADC."""
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default()
        creds.refresh(google.auth.transport.requests.Request())
        token_path = Path("/tmp/gcloud_token")  # noqa: S108
        token_path.write_text(creds.token)
        subprocess.run(  # noqa: S603
            ["gcloud", "config", "set", "auth/access_token_file", str(token_path)],  # noqa: S607
            capture_output=True,
        )
        subprocess.run(  # noqa: S603
            ["gcloud", "config", "set", "project", PROJECT_ID],  # noqa: S607
            capture_output=True,
        )
    except Exception as e:
        print(f"Warning: could not refresh token: {e}")


def fetch_logs(service: str, limit: int) -> str:
    """Fetch recent logs from Cloud Run."""
    result = subprocess.run(  # noqa: S603
        [  # noqa: S607
            "gcloud",
            "run",
            "services",
            "logs",
            "read",
            service,
            "--project",
            PROJECT_ID,
            "--region",
            REGION,
            "--limit",
            str(limit),
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout


def parse_runs(log_text: str) -> list[dict]:
    """Parse competition runs from log text."""
    runs = []
    lines = log_text.split("\n")

    current_run: dict | None = None

    for line in lines:
        # Detect competition run start
        if "COMPETITION_RUN" in line:
            prompt_match = re.search(r'prompt="(.+?)" base_url=(.+)', line)
            if prompt_match:
                ts_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                current_run = {
                    "timestamp": ts_match.group(1) if ts_match else "",
                    "prompt": prompt_match.group(1).encode().decode("unicode_escape"),
                    "base_url": prompt_match.group(2).strip(),
                    "api_calls": [],
                    "errors": [],
                }

        # Detect classification
        if current_run and "Classified as task_type=" in line:
            match = re.search(r"task_type=(\S+) params=(.+)", line)
            if match:
                current_run["task_type"] = match.group(1)
                try:
                    raw = match.group(2)
                    raw = raw.replace("'", '"').replace("True", "true")
                    raw = raw.replace("False", "false").replace("None", "null")
                    current_run["params"] = json.loads(raw)
                except json.JSONDecodeError:
                    current_run["params_raw"] = match.group(2)

        # Detect API calls
        if current_run and re.search(r"API (GET|POST|PUT|DELETE) .+ -> \d+", line):
            api_match = re.search(r"API (GET|POST|PUT|DELETE) (\S+) -> (\d+) \((\d+\.\d+)s\)", line)
            if api_match:
                call = {
                    "method": api_match.group(1),
                    "endpoint": api_match.group(2),
                    "status": int(api_match.group(3)),
                    "duration_s": float(api_match.group(4)),
                }
                current_run["api_calls"].append(call)
                if call["status"] >= 400:
                    current_run["errors"].append(call)

        # Detect API errors with details
        if current_run and "API error" in line:
            err_match = re.search(r"API error (\d+) on (\S+ \S+): (.+)", line)
            if err_match:
                current_run.setdefault("error_details", []).append(
                    {
                        "status": int(err_match.group(1)),
                        "endpoint": err_match.group(2),
                        "message": err_match.group(3),
                    }
                )

        # Detect handler result (end of run)
        if current_run and "Handler result" in line:
            match = re.search(
                r"task_type=(\S+) handler=(\S+) api_calls=(\d+) duration=(\d+\.\d+)s result=(.+)",
                line,
            )
            if match:
                current_run["handler"] = match.group(2)
                current_run["total_api_calls"] = int(match.group(3))
                current_run["total_duration_s"] = float(match.group(4))
                try:
                    raw = match.group(5)
                    raw = raw.replace("'", '"').replace("True", "true")
                    raw = raw.replace("False", "false").replace("None", "null")
                    current_run["result"] = json.loads(raw)
                except json.JSONDecodeError:
                    current_run["result_raw"] = match.group(5)
                runs.append(current_run)
                current_run = None

        # Detect router error (failed run)
        if current_run and "Router error" in line:
            current_run["status"] = "error"
            runs.append(current_run)
            current_run = None

    return runs


def save_runs(runs: list[dict], service: str) -> int:
    """Save runs to JSON files. Returns count of new runs saved."""
    RUNS_DIR.mkdir(exist_ok=True)
    saved = 0

    for run in runs:
        ts = run.get("timestamp", "unknown").replace(" ", "_").replace(":", "-")
        task = run.get("task_type", "unknown")
        filename = f"{ts}_{task}_{service}.json"
        filepath = RUNS_DIR / filename

        if filepath.exists():
            continue

        run["service"] = service
        with open(filepath, "w") as f:
            json.dump(run, f, indent=2, ensure_ascii=False)
        saved += 1
        status = "ERROR" if run.get("errors") or run.get("status") == "error" else "OK"
        calls = run.get("total_api_calls", "?")
        duration = run.get("total_duration_s", "?")
        print(f"  [{status}] {task} — {calls} calls, {duration}s — {filename}")

    return saved


def print_summary(runs: list[dict]) -> None:
    """Print a summary of all captured runs."""
    if not runs:
        print("No competition runs found in logs.")
        return

    print(f"\n{'=' * 70}")
    print(f"Found {len(runs)} competition runs:")
    print(f"{'=' * 70}")
    for run in runs:
        task = run.get("task_type", "unknown")
        calls = run.get("total_api_calls", "?")
        errors = len(run.get("errors", []))
        duration = run.get("total_duration_s", "?")
        status = "FAIL" if run.get("status") == "error" or errors else "OK"
        prompt_preview = run.get("prompt", "")[:60]
        print(f"  [{status}] {task:30s} calls={calls} errors={errors} time={duration}s")
        print(f"         {prompt_preview}...")


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture competition runs from Cloud Run logs")
    parser.add_argument(
        "--service",
        default="tripletex-agent",
        help="Cloud Run service name",
    )
    parser.add_argument("--limit", type=int, default=500, help="Number of log lines to fetch")
    args = parser.parse_args()

    print(f"Fetching logs from {args.service}...")
    refresh_token()
    log_text = fetch_logs(args.service, args.limit)
    runs = parse_runs(log_text)
    print_summary(runs)

    saved = save_runs(runs, args.service)
    print(f"\nSaved {saved} new runs to {RUNS_DIR}/")
    if saved:
        print("Commit and push to share with teammates:")
        print("  git add runs/ && git commit -m 'Add competition runs' && git push")


if __name__ == "__main__":
    main()
