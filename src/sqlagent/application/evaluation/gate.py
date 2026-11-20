"""Regression gate comparing a run against the committed baseline (D20/S26)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_EPSILON = 1e-12
_CATEGORY_PREFIX = "by_category."


@dataclass(frozen=True, slots=True)
class GateRegression:
    """One metric that dropped more than the allowed tolerance."""

    metric: str
    baseline: float
    current: float
    max_drop: float

    @property
    def drop(self) -> float:
        return self.baseline - self.current

    def render(self) -> str:
        return (
            f"REGRESSION {self.metric}: baseline {self.baseline:.4f} -> "
            f"current {self.current:.4f} (drop {self.drop:.4f} > {self.max_drop:.4f})"
        )


@dataclass(frozen=True, slots=True)
class GateImprovement:
    """One metric that improved over the baseline (informational)."""

    metric: str
    baseline: float
    current: float


@dataclass(frozen=True, slots=True)
class GateReport:
    """Outcome of comparing the current summary with the baseline."""

    ok: bool
    regressions: tuple[GateRegression, ...]
    improvements: tuple[GateImprovement, ...]
    checked: tuple[str, ...]

    def render(self) -> tuple[str, ...]:
        lines = [regression.render() for regression in self.regressions]
        if self.ok and self.improvements:
            lines.extend(
                f"IMPROVEMENT {item.metric}: {item.baseline:.4f} -> {item.current:.4f}"
                for item in self.improvements
            )
        return tuple(lines)


def _metric_value(metrics: Mapping[str, Any], path: tuple[str, ...]) -> float | None:
    node: Any = metrics
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    return float(node)


def _collect_metrics(baseline: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    metrics: list[str] = ["overall.ex", "overall.refusal_acc"]
    baseline_categories = baseline.get("by_category", {})
    current_categories = current.get("by_category", {})
    if isinstance(baseline_categories, Mapping) and isinstance(current_categories, Mapping):
        for category in baseline_categories:
            if category in current_categories:
                metrics.append(f"{_CATEGORY_PREFIX}{category}.ex")
    return metrics


def _path_for(metric: str) -> tuple[str, ...]:
    if metric.startswith(_CATEGORY_PREFIX):
        remainder = metric[len(_CATEGORY_PREFIX) :]
        category, _, leaf = remainder.rpartition(".")
        return ("by_category", category, leaf)
    head, _, leaf = metric.rpartition(".")
    return (head, leaf)


def compare_summaries(
    baseline: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    max_drop: float = 0.0,
) -> GateReport:
    """Compare overall EX, refusal accuracy and per-category EX (D20).

    A metric fails when ``current < baseline - max_drop``.  Metrics missing from
    either side (for example when ``--limit`` filters out a category) are skipped
    and listed in ``checked`` only when they were comparable.
    """

    baseline_metrics = baseline.get("metrics", {})
    current_metrics = current.get("metrics", {})
    if not isinstance(baseline_metrics, Mapping) or not isinstance(current_metrics, Mapping):
        return GateReport(ok=False, regressions=(), improvements=(), checked=())

    regressions: list[GateRegression] = []
    improvements: list[GateImprovement] = []
    checked: list[str] = []
    for metric in _collect_metrics(baseline_metrics, current_metrics):
        path = _path_for(metric)
        old_value = _metric_value(baseline_metrics, path)
        new_value = _metric_value(current_metrics, path)
        if old_value is None or new_value is None:
            continue
        checked.append(metric)
        if new_value < old_value - max_drop - _EPSILON:
            regressions.append(GateRegression(metric, old_value, new_value, max_drop))
        elif new_value > old_value + _EPSILON:
            improvements.append(GateImprovement(metric, old_value, new_value))
    return GateReport(
        ok=not regressions,
        regressions=tuple(regressions),
        improvements=tuple(improvements),
        checked=tuple(checked),
    )


__all__ = [
    "GateImprovement",
    "GateRegression",
    "GateReport",
    "compare_summaries",
]
