"""Execution-accuracy scoring, confidence intervals and aggregate metrics (D19/S24).

The module is deliberately pure apart from reading the domain answer model: the
runner executes SQL, this module decides what is correct.  Every number is
derived from per-item :class:`ItemResult` records so a summary can be rebuilt
from ``results.jsonl`` without rerunning the agent.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import ceil, sqrt
from statistics import mean
from typing import Any

from sqlagent.application.evaluation.benchmark import (
    BenchmarkItem,
    Category,
    Difficulty,
    Expect,
)
from sqlagent.domain.equivalence import results_equivalent
from sqlagent.domain.errors import GuardrailCode
from sqlagent.domain.models import AgentAnswer, Language, Status

Z_95 = 1.959963984540054

FAILURE_ORDER: tuple[str, ...] = (
    "protocol_error",
    "guardrail_block",
    "execution_error",
    "wrong_tables",
    "wrong_result",
    "refusal_mismatch",
    "timeout",
)

_GUARDRAIL_CODES = frozenset(code.value for code in GuardrailCode)

CATEGORY_ORDER: tuple[str, ...] = tuple(category.value for category in Category)
LANGUAGE_ORDER: tuple[str, ...] = tuple(language.value for language in Language)
DIFFICULTY_ORDER: tuple[str, ...] = tuple(difficulty.value for difficulty in Difficulty)


@dataclass(frozen=True, slots=True)
class ItemResult:
    """Everything the summary and reports need about one benchmark item."""

    id: str
    category: str
    difficulty: str
    lang: str
    expect: str
    question: str
    status: str
    sql: str | None
    gold_sql: str | None
    executed: bool
    ex: bool | None
    expected_ok: bool
    first_attempt_ex: bool | None
    valid_sql: bool
    attempts: int
    failure: str | None
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    retrieved_tables: tuple[str, ...] = ()
    gold_tables: tuple[str, ...] = ()
    guardrail_events: tuple[str, ...] = ()
    pair_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation (tuples become lists)."""

        return {
            "id": self.id,
            "category": self.category,
            "difficulty": self.difficulty,
            "lang": self.lang,
            "expect": self.expect,
            "question": self.question,
            "status": self.status,
            "sql": self.sql,
            "gold_sql": self.gold_sql,
            "executed": self.executed,
            "ex": self.ex,
            "expected_ok": self.expected_ok,
            "first_attempt_ex": self.first_attempt_ex,
            "valid_sql": self.valid_sql,
            "attempts": self.attempts,
            "failure": self.failure,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "retrieved_tables": list(self.retrieved_tables),
            "gold_tables": list(self.gold_tables),
            "guardrail_events": list(self.guardrail_events),
            "pair_id": self.pair_id,
        }


def _round(value: float) -> float:
    return round(float(value), 6)


def _rate(numerator: int, denominator: int, *, empty: float = 1.0) -> float:
    if denominator <= 0:
        return empty
    return _round(numerator / denominator)


def wilson_interval(successes: int, total: int, *, z: float = Z_95) -> tuple[float, float]:
    """Return the Wilson score interval for a binomial proportion (S24).

    ``total == 0`` returns ``(0.0, 0.0)``; the aggregate layer only calls this
    when there is at least one observation.
    """

    if total <= 0:
        return (0.0, 0.0)
    proportion = successes / total
    denominator = 1.0 + (z * z) / total
    centre = (proportion + (z * z) / (2.0 * total)) / denominator
    margin = (
        z
        * sqrt(proportion * (1.0 - proportion) / total + (z * z) / (4.0 * total * total))
        / denominator
    )
    low = max(0.0, centre - margin)
    high = min(1.0, centre + margin)
    if successes <= 0:
        low = 0.0
    if successes >= total:
        high = 1.0
    return (low, high)


def nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    """Return the nearest-rank percentile (D19: no interpolation)."""

    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    bounded = min(100.0, max(0.0, percentile))
    rank = max(1, ceil(bounded / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _is_executed(answer: AgentAnswer) -> bool:
    return answer.status is Status.OK and answer.result is not None


def expected_behaviour_ok(item: BenchmarkItem, answer: AgentAnswer, ex: bool | None) -> bool:
    """Whether the answer meets the D19 expectation for this item."""

    executed = _is_executed(answer)
    if item.expect is Expect.ANSWER:
        return bool(ex)
    if item.expect is Expect.CLARIFICATION:
        return answer.status is Status.CLARIFICATION and not executed
    if item.expect is Expect.UNANSWERABLE:
        return answer.status in {Status.CLARIFICATION, Status.REFUSED} and not executed
    return answer.status is Status.REFUSED


def classify_failure(  # noqa: PLR0911, PLR0913 - explicit diagnostics inputs
    item: BenchmarkItem,
    answer: AgentAnswer,
    *,
    ex: bool | None,
    executed: bool,
    predicted_tables: Sequence[str],
    gold_tables: Sequence[str],
) -> str | None:
    """Return the D19 failure-taxonomy label for an incorrect item."""

    if item.expect is not Expect.ANSWER:
        return "refusal_mismatch"
    if answer.status in {Status.REFUSED, Status.CLARIFICATION}:
        return "refusal_mismatch"

    trace = answer.trace
    messages = [(attempt.error_message or "").casefold() for attempt in trace.attempts]
    if any("timeout" in message or "timed out" in message for message in messages):
        return "timeout"
    if trace.guardrail_events or any(
        attempt.error_code in _GUARDRAIL_CODES for attempt in trace.attempts
    ):
        return "guardrail_block"
    if any(attempt.error_code == "EXECUTION_ERROR" for attempt in trace.attempts):
        return "execution_error"
    if answer.status is Status.FAILED and not trace.attempts:
        return "protocol_error"
    if executed:
        if {name.casefold() for name in predicted_tables} != {
            name.casefold() for name in gold_tables
        }:
            return "wrong_tables"
        return "wrong_result"
    del ex  # only the caller's correctness decision is needed beyond this point
    return "protocol_error"


def score_item(  # noqa: PLR0913 - explicit scoring inputs
    item: BenchmarkItem,
    answer: AgentAnswer,
    *,
    gold_rows: Sequence[Sequence[Any]] | None = None,
    gold_ordered: bool = False,
    gold_tables: Sequence[str] = (),
    predicted_tables: Sequence[str] = (),
    latency_ms: float = 0.0,
) -> ItemResult:
    """Score one answer against the gold rows and D19 expectation rules."""

    executed = _is_executed(answer)
    ex: bool | None = None
    if item.expect is Expect.ANSWER:
        rows = gold_rows if gold_rows is not None else ()
        ex = bool(
            executed
            and answer.result is not None
            and results_equivalent(rows, answer.result.rows, gold_ordered)
        )
    expected_ok = expected_behaviour_ok(item, answer, ex)
    first_attempt_ex: bool | None = None
    if item.expect is Expect.ANSWER:
        first_attempt_ex = bool(
            ex and answer.trace.attempts and answer.trace.attempts[0].error_code is None
        )
    failure = (
        None
        if expected_ok
        else classify_failure(
            item,
            answer,
            ex=ex,
            executed=executed,
            predicted_tables=predicted_tables,
            gold_tables=gold_tables,
        )
    )
    return ItemResult(
        id=item.id,
        category=item.category.value,
        difficulty=item.difficulty.value,
        lang=item.lang.value,
        expect=item.expect.value,
        question=item.question,
        status=answer.status.value,
        sql=answer.sql,
        gold_sql=item.gold_sql,
        executed=executed,
        ex=ex,
        expected_ok=expected_ok,
        first_attempt_ex=first_attempt_ex,
        valid_sql=executed,
        attempts=len(answer.trace.attempts),
        failure=failure,
        latency_ms=_round(latency_ms),
        prompt_tokens=answer.trace.usage.prompt,
        completion_tokens=answer.trace.usage.completion,
        retrieved_tables=tuple(answer.trace.retrieved_tables),
        gold_tables=tuple(gold_tables),
        guardrail_events=tuple(answer.trace.guardrail_events),
        pair_id=item.pair_id,
    )


def _bucket(
    results: Sequence[ItemResult],
    attribute: str,
    order: Sequence[str],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[ItemResult]] = {}
    for result in results:
        grouped.setdefault(getattr(result, attribute), []).append(result)
    keys = [key for key in order if key in grouped]
    keys.extend(sorted(key for key in grouped if key not in order))
    buckets: dict[str, dict[str, Any]] = {}
    for key in keys:
        group = grouped[key]
        answerable = [result for result in group if result.ex is not None]
        if answerable:
            correct = sum(1 for result in answerable if result.ex)
            n = len(answerable)
        else:
            correct = sum(1 for result in group if result.expected_ok)
            n = len(group)
        low, high = wilson_interval(correct, n)
        buckets[key] = {
            "n": len(group),
            "n_answerable": len(answerable),
            "correct": correct,
            "ex": _rate(correct, n),
            "ex_ci_low": _round(low),
            "ex_ci_high": _round(high),
            "expectation_acc": _rate(sum(1 for result in group if result.expected_ok), len(group)),
        }
    return buckets


def _pair_consistency(results: Sequence[ItemResult]) -> float:
    pairs: dict[str, list[ItemResult]] = {}
    for result in results:
        if result.pair_id is not None and result.ex is not None:
            pairs.setdefault(result.pair_id, []).append(result)
    eligible = [members for members in pairs.values() if any(member.ex for member in members)]
    if not eligible:
        return 1.0
    consistent = sum(1 for members in eligible if all(member.ex for member in members))
    return _rate(consistent, len(eligible))


def _retrieval_recall(results: Sequence[ItemResult]) -> float:
    recalls: list[float] = []
    for result in results:
        if result.ex is None or not result.gold_tables:
            continue
        gold = set(result.gold_tables)
        found = len(gold & set(result.retrieved_tables))
        recalls.append(found / len(gold))
    if not recalls:
        return 1.0
    return _round(mean(recalls))


def _failure_taxonomy(results: Sequence[ItemResult]) -> dict[str, int]:
    counts = Counter(result.failure for result in results if result.failure is not None)
    ordered = {name: counts[name] for name in FAILURE_ORDER if counts[name]}
    ordered.update({name: count for name, count in sorted(counts.items()) if name not in ordered})
    return ordered


def aggregate_metrics(results: Sequence[ItemResult]) -> dict[str, Any]:
    """Aggregate S24 metrics and breakdowns from per-item results."""

    answerable = [result for result in results if result.ex is not None]
    n_answerable = len(answerable)
    correct = sum(1 for result in answerable if result.ex)
    ex = _rate(correct, n_answerable)
    ci_low, ci_high = wilson_interval(correct, n_answerable)
    first_correct = sum(1 for result in answerable if result.first_attempt_ex is True)
    first_attempt_ex = _rate(first_correct, n_answerable)
    valid_sql = sum(1 for result in answerable if result.valid_sql)

    refusal_items = [result for result in results if result.expect == Expect.REFUSAL.value]
    clarification_items = [
        result for result in results if result.expect == Expect.CLARIFICATION.value
    ]
    unanswerable_items = [
        result for result in results if result.expect == Expect.UNANSWERABLE.value
    ]
    latencies = [result.latency_ms for result in results]
    prompt_total = sum(result.prompt_tokens for result in results)
    completion_total = sum(result.completion_tokens for result in results)
    attempts_total = sum(result.attempts for result in answerable)

    overall = {
        "included": len(results),
        "n": n_answerable,
        "correct": correct,
        "ex": ex,
        "ex_ci_low": _round(ci_low),
        "ex_ci_high": _round(ci_high),
        "valid_sql_rate": _rate(valid_sql, n_answerable),
        "first_attempt_ex": first_attempt_ex,
        "repair_uplift": _round(ex - first_attempt_ex),
        "refusal_acc": _rate(
            sum(1 for result in refusal_items if result.expected_ok), len(refusal_items)
        ),
        "clarification_acc": _rate(
            sum(1 for result in clarification_items if result.expected_ok),
            len(clarification_items),
        ),
        "unanswerable_acc": _rate(
            sum(1 for result in unanswerable_items if result.expected_ok),
            len(unanswerable_items),
        ),
        "pair_consistency": _pair_consistency(results),
        "retrieval_table_recall": _retrieval_recall(results),
        "mean_attempts": _rate(attempts_total, n_answerable, empty=0.0),
        "latency_ms": {
            "mean": _round(mean(latencies)) if latencies else 0.0,
            "p50": _round(nearest_rank_percentile(latencies, 50)),
            "p95": _round(nearest_rank_percentile(latencies, 95)),
        },
        "tokens": {
            "prompt_total": prompt_total,
            "completion_total": completion_total,
            "prompt_per_question": _rate(prompt_total, len(results), empty=0.0),
            "completion_per_question": _rate(completion_total, len(results), empty=0.0),
        },
    }
    return {
        "overall": overall,
        "by_category": _bucket(results, "category", CATEGORY_ORDER),
        "by_language": _bucket(results, "lang", LANGUAGE_ORDER),
        "by_difficulty": _bucket(results, "difficulty", DIFFICULTY_ORDER),
        "failure_taxonomy": _failure_taxonomy(results),
    }


def iter_failures(results: Iterable[ItemResult]) -> Iterable[ItemResult]:
    """Yield the incorrect items in benchmark order (report helper)."""

    return (result for result in results if not result.expected_ok)


__all__ = [
    "CATEGORY_ORDER",
    "DIFFICULTY_ORDER",
    "FAILURE_ORDER",
    "LANGUAGE_ORDER",
    "ItemResult",
    "aggregate_metrics",
    "classify_failure",
    "expected_behaviour_ok",
    "iter_failures",
    "nearest_rank_percentile",
    "score_item",
    "wilson_interval",
]
