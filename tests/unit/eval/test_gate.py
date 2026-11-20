"""Unit tests for the D20 regression gate."""

from __future__ import annotations

import pytest

from sqlagent.application.evaluation.gate import compare_summaries

pytestmark = pytest.mark.unit


def summary_data(
    *,
    ex: float = 1.0,
    refusal: float = 1.0,
    categories: dict[str, float] | None = None,
) -> dict[str, object]:
    by_category = {
        "aggregation": {"ex": 1.0},
        "filtering": {"ex": 1.0},
        "join": {"ex": 1.0},
    }
    by_category.update({name: {"ex": value} for name, value in (categories or {}).items()})
    return {
        "schema": "sqlagent.eval-summary/v1",
        "metrics": {
            "overall": {"ex": ex, "refusal_acc": refusal},
            "by_category": by_category,
        },
    }


def test_gate_passes_when_metrics_are_equal() -> None:
    report = compare_summaries(summary_data(), summary_data())
    assert report.ok is True
    assert report.regressions == ()
    assert report.checked


def test_gate_fails_on_overall_ex_drop() -> None:
    report = compare_summaries(summary_data(ex=1.0), summary_data(ex=0.8))
    assert report.ok is False
    assert [regression.metric for regression in report.regressions] == ["overall.ex"]
    assert report.regressions[0].baseline == 1.0
    assert report.regressions[0].current == 0.8


def test_gate_tolerates_drop_up_to_max_drop() -> None:
    report = compare_summaries(summary_data(ex=1.0), summary_data(ex=0.9), max_drop=0.1)
    assert report.ok is True
    report = compare_summaries(summary_data(ex=1.0), summary_data(ex=0.89), max_drop=0.1)
    assert report.ok is False


def test_gate_fails_on_refusal_accuracy_and_category_drops() -> None:
    report = compare_summaries(
        summary_data(refusal=1.0, categories={"aggregation": 1.0}),
        summary_data(refusal=0.5, categories={"aggregation": 0.5}),
    )
    assert report.ok is False
    metrics = {regression.metric for regression in report.regressions}
    assert metrics == {
        "overall.refusal_acc",
        "by_category.aggregation.ex",
    }


def test_gate_reports_improvements_and_skips_missing_categories() -> None:
    current = summary_data(ex=1.0, categories={"aggregation": 1.0})
    current["metrics"]["by_category"].pop("join")  # type: ignore[index]
    baseline = summary_data(ex=0.9, categories={"aggregation": 0.9})
    report = compare_summaries(baseline, current)
    assert report.ok is True
    improvements = {item.metric for item in report.improvements}
    assert "overall.ex" in improvements
    assert "by_category.aggregation.ex" in improvements
    assert all(not metric.startswith("by_category.join") for metric in report.checked)


def test_gate_can_read_summary_objects() -> None:
    baseline = summary_data()
    report = compare_summaries(baseline, baseline)
    assert report.ok is True
