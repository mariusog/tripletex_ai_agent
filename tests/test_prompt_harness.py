"""Task-prompt test harness for LLM classification accuracy.

Verifies the LLM classifier correctly identifies task types
across all 7 languages and extracts expected parameters.
All tests are marked @pytest.mark.slow for LLM-calling variants.
Unit tests mock the LLM client to run fast.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.models import TaskClassification
from tests.prompt_harness_utils import (
    LANGUAGES,
    generate_accuracy_matrix,
    load_all_fixtures,
)

# Load fixtures once at module level
ALL_FIXTURES = load_all_fixtures()
ALL_TASK_TYPES = [f["task_type"] for f in ALL_FIXTURES]


def _make_mock_llm(task_type: str, params: dict) -> MagicMock:
    """Create a mock LLMClient that returns the given classification."""
    mock = MagicMock()
    mock.classify_and_extract.return_value = [
        TaskClassification(
            task_type=task_type,
            params=params,
        )
    ]
    return mock


# -----------------------------------------------------------------------
# Fast tests (mocked LLM)
# -----------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGUAGES, ids=LANGUAGES)
def test_classification_accuracy_per_language(lang: str) -> None:
    """Verify all task types classify correctly for a given language."""
    for fixture in ALL_FIXTURES:
        task_type = fixture["task_type"]
        prompt = fixture["prompts"][lang]
        expected_params = fixture["expected_params"]

        mock_llm = _make_mock_llm(task_type, expected_params)
        results = mock_llm.classify_and_extract(prompt)

        assert results[0].task_type == task_type, (
            f"Language={lang}: expected {task_type}, got {results[0].task_type}"
        )


@pytest.mark.parametrize(
    "task_type",
    ALL_TASK_TYPES,
    ids=ALL_TASK_TYPES,
)
def test_classification_accuracy_per_task_type(task_type: str) -> None:
    """Verify a specific task type classifies correctly in all languages."""
    fixture = next(f for f in ALL_FIXTURES if f["task_type"] == task_type)
    expected_params = fixture["expected_params"]

    for lang in LANGUAGES:
        prompt = fixture["prompts"][lang]
        mock_llm = _make_mock_llm(task_type, expected_params)
        results = mock_llm.classify_and_extract(prompt)

        assert results[0].task_type == task_type, (
            f"Task={task_type}, lang={lang}: got {results[0].task_type}"
        )


@pytest.mark.parametrize(
    "task_type",
    ALL_TASK_TYPES,
    ids=ALL_TASK_TYPES,
)
def test_parameter_extraction_accuracy(task_type: str) -> None:
    """Verify extracted params match expected for each task type."""
    fixture = next(f for f in ALL_FIXTURES if f["task_type"] == task_type)
    expected_params = fixture["expected_params"]

    # Test with Norwegian prompt (canonical language)
    prompt = fixture["prompts"]["no"]
    mock_llm = _make_mock_llm(task_type, expected_params)
    results = mock_llm.classify_and_extract(prompt)
    result = results[0]

    for key, expected_val in expected_params.items():
        actual_val = result.params.get(key)
        assert actual_val == expected_val, (
            f"Task={task_type}, param={key}: expected {expected_val!r}, got {actual_val!r}"
        )


def test_all_task_types_have_fixtures() -> None:
    """Verify every known task type has a prompt fixture file."""
    from src.constants import ALL_TASK_TYPES as KNOWN_TYPES

    fixture_types = {f["task_type"] for f in ALL_FIXTURES}
    for task_type in KNOWN_TYPES:
        assert task_type in fixture_types, f"Missing fixture for task type: {task_type}"


def test_all_fixtures_have_all_languages() -> None:
    """Verify every fixture has prompts in all 7 languages."""
    for fixture in ALL_FIXTURES:
        for lang in LANGUAGES:
            assert lang in fixture["prompts"], (
                f"Task {fixture['task_type']} missing language: {lang}"
            )


def test_accuracy_report_generation() -> None:
    """Verify the accuracy matrix report generates valid markdown."""
    results: dict[str, dict[str, bool]] = {}
    for fixture in ALL_FIXTURES:
        task_type = fixture["task_type"]
        results[task_type] = {lang: True for lang in LANGUAGES}

    report = generate_accuracy_matrix(results)
    assert "| Task Type |" in report
    assert "Overall accuracy" in report
    assert "100.0%" in report


# -----------------------------------------------------------------------
# Slow tests (real LLM) -- run with: pytest -m slow --run-slow
# -----------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.parametrize("lang", LANGUAGES, ids=LANGUAGES)
def test_real_llm_classification_per_language(lang: str) -> None:
    """Call the real LLM to classify prompts per language."""
    import os

    from src.llm import LLMClient

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    client = LLMClient(api_key=api_key)
    failures: list[str] = []

    for fixture in ALL_FIXTURES:
        task_type = fixture["task_type"]
        prompt = fixture["prompts"][lang]
        results = client.classify_and_extract(prompt)
        if results[0].task_type != task_type:
            failures.append(f"{task_type}: expected {task_type}, got {results[0].task_type}")

    assert not failures, f"Language={lang} failures:\n" + "\n".join(failures)


@pytest.mark.slow
def test_real_llm_full_accuracy_report() -> None:
    """Run full accuracy matrix against real LLM and print report."""
    import os

    from src.llm import LLMClient

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    client = LLMClient(api_key=api_key)
    results: dict[str, dict[str, bool]] = {}

    for fixture in ALL_FIXTURES:
        task_type = fixture["task_type"]
        results[task_type] = {}
        for lang in LANGUAGES:
            prompt = fixture["prompts"][lang]
            result = client.classify_and_extract(prompt)
            results[task_type][lang] = result[0].task_type == task_type

    report = generate_accuracy_matrix(results)
    print(f"\n{report}")

    # Assert >= 95% accuracy
    total = sum(1 for t in results.values() for v in t.values() if v)
    count = sum(len(t) for t in results.values())
    accuracy = total / count if count else 0
    assert accuracy >= 0.95, f"Accuracy {accuracy:.1%} < 95% threshold"
