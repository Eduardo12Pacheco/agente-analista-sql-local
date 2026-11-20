"""Bounded evaluation runner: executes gold SQL and scores agent answers (D19).

The runner is the only evaluation component that touches the warehouse.  Gold
results are obtained through the same locked-down read-only connection as the
agent, so both sides of the comparison see identical data and types.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence

import sqlglot

from sqlagent.application.evaluation.benchmark import BenchmarkItem, Expect
from sqlagent.application.evaluation.metrics import ItemResult, score_item
from sqlagent.application.ports import (
    BackendInfo,
    LLMPort,
    LLMRequest,
    LLMResponse,
    WarehousePort,
)
from sqlagent.domain.errors import (
    ConfigError,
    GuardrailViolation,
    SqlAgentError,
    SqlExecutionError,
)
from sqlagent.domain.sql_policy import SqlPolicy


def has_top_level_order(sql: str) -> bool:
    """Return whether ``sql`` has a top-level ORDER BY (D19 comparisons)."""

    try:
        expression = sqlglot.parse_one(sql, read="duckdb")
    except sqlglot.errors.SqlglotError:  # pragma: no cover - gold SQL is validated first
        return False
    order = expression.args.get("order")
    return order is not None


class TrackingLLM:
    """Decorator remembering the last backend error (cassette-miss detection).

    The agent intentionally converts ``LLMError`` into a friendly ``failed``
    answer, so the CLI cannot see a ``CassetteMiss`` from the answer alone.  This
    thin decorator records the typed error for the evaluation adapter, which then
    maps a stale cassette to exit code 4 (D25).
    """

    def __init__(self, inner: LLMPort) -> None:
        self.inner = inner
        self.last_error: SqlAgentError | None = None

    def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            return self.inner.complete(request)
        except SqlAgentError as exc:
            self.last_error = exc
            raise

    def describe(self) -> BackendInfo:
        return self.inner.describe()


class EvaluationRunner:
    """Run benchmark items single-turn and turn answers into ``ItemResult``s."""

    def __init__(
        self,
        agent: object,
        warehouse: WarehousePort,
        policy: SqlPolicy,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        """``agent`` is an ``AnalystAgent``; kept loose to avoid a circular import."""

        self._agent = agent
        self._warehouse = warehouse
        self._policy = policy
        self._clock = clock

    def run(self, items: Sequence[BenchmarkItem]) -> tuple[ItemResult, ...]:
        """Score every item in benchmark order."""

        results: list[ItemResult] = []
        for item in items:
            gold_rows, gold_ordered, gold_tables = self._gold(item)
            started = self._clock()
            answer = self._agent.run(item.question, language=item.lang)  # type: ignore[attr-defined]
            latency_ms = (self._clock() - started) * 1000.0
            predicted_tables = self._predicted_tables(answer.sql)
            results.append(
                score_item(
                    item,
                    answer,
                    gold_rows=gold_rows,
                    gold_ordered=gold_ordered,
                    gold_tables=gold_tables,
                    predicted_tables=predicted_tables,
                    latency_ms=latency_ms,
                )
            )
        return tuple(results)

    def _gold(
        self, item: BenchmarkItem
    ) -> tuple[tuple[tuple[object, ...], ...] | None, bool, tuple[str, ...]]:
        if item.expect is not Expect.ANSWER:
            return None, False, ()
        assert item.gold_sql is not None  # noqa: S101 - schema guarantees it
        validated = self._policy.validate(item.gold_sql)
        try:
            result = self._warehouse.execute(validated)
        except SqlExecutionError as exc:
            raise ConfigError(f"gold SQL for {item.id} failed to execute: {exc}") from exc
        return result.rows, has_top_level_order(item.gold_sql), validated.tables

    def _predicted_tables(self, sql: str | None) -> tuple[str, ...]:
        if not sql:
            return ()
        try:
            return self._policy.validate(sql).tables
        except GuardrailViolation:  # pragma: no cover - agent only exposes validated SQL
            return ()


__all__ = ["EvaluationRunner", "TrackingLLM", "has_top_level_order"]
