"""Utilities for the task-prompt test harness.

Loads prompt fixtures and generates accuracy report matrices.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "prompts"

LANGUAGES = ["no", "en", "es", "pt", "nn", "de", "fr"]


def load_all_fixtures() -> list[dict[str, Any]]:
    """Load all prompt fixture JSON files from the fixtures directory.

    Returns a list of dicts, each with task_type, prompts, expected_params.
    """
    fixtures: list[dict[str, Any]] = []
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        with open(path) as f:
            fixtures.append(json.load(f))
    return fixtures


def load_fixture(task_type: str) -> dict[str, Any]:
    """Load a single prompt fixture by task type name."""
    path = FIXTURES_DIR / f"{task_type}.json"
    with open(path) as f:
        return json.load(f)


def generate_accuracy_matrix(
    results: dict[str, dict[str, bool]],
) -> str:
    """Generate a markdown accuracy matrix from classification results.

    Args:
        results: Nested dict of {task_type: {language: passed_bool}}.

    Returns:
        Markdown table string with task_type rows and language columns.
    """
    task_types = sorted(results.keys())
    if not task_types:
        return "No results to report."

    # Header
    header = "| Task Type | " + " | ".join(LANGUAGES) + " | Accuracy |"
    separator = "|---|" + "|".join(["---"] * len(LANGUAGES)) + "|---|"
    lines = [header, separator]

    total_pass = 0
    total_count = 0

    for task_type in task_types:
        lang_results = results[task_type]
        cells = []
        pass_count = 0
        for lang in LANGUAGES:
            passed = lang_results.get(lang, False)
            cells.append("Y" if passed else "N")
            if passed:
                pass_count += 1
        accuracy = pass_count / len(LANGUAGES) * 100
        total_pass += pass_count
        total_count += len(LANGUAGES)
        row = f"| {task_type} | " + " | ".join(cells) + f" | {accuracy:.0f}% |"
        lines.append(row)

    # Summary row
    overall = total_pass / total_count * 100 if total_count else 0
    summary = f"\n**Overall accuracy**: {total_pass}/{total_count} ({overall:.1f}%)"
    lines.append(summary)

    return "\n".join(lines)
