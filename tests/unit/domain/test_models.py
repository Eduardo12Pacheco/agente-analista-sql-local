"""Domain models and error hierarchy."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from sqlagent.domain.errors import (
    CassetteMiss,
    ConfigError,
    GuardrailCode,
    GuardrailViolation,
    LLMError,
    LLMProtocolError,
    QueryTimeoutError,
    SqlAgentError,
    SqlExecutionError,
    WarehouseUnavailable,
)
from sqlagent.domain.models import (
    AgentAnswer,
    AttemptRecord,
    ChartSpec,
    ColumnInfo,
    Language,
    PhaseTiming,
    QueryResult,
    Status,
    TokenUsage,
    Trace,
)

pytestmark = pytest.mark.unit
EXPECTED_TOTAL_TOKENS = 25
EXPECTED_ROW_COUNT = 2
EXPECTED_ELAPSED_MS = 12.5
PHASE_ELAPSED_MS = 3.5


def test_language_and_status_values() -> None:
    assert {language.value for language in Language} == {"es", "en"}
    assert {status.value for status in Status} == {"ok", "clarification", "refused", "failed"}


def test_token_usage_adds_componentwise_and_reports_total() -> None:
    left = TokenUsage(prompt=10, completion=3)
    right = TokenUsage(prompt=5, completion=7)

    combined = left + right

    assert combined == TokenUsage(prompt=15, completion=10)
    assert combined.total == EXPECTED_TOTAL_TOKENS
    assert TokenUsage().total == 0
    assert left + TokenUsage() == left


def test_column_info_and_query_result_shape() -> None:
    columns = (ColumnInfo(name="n", type="BIGINT"),)
    result = QueryResult(
        columns=columns,
        rows=((1,), (2,)),
        row_count=2,
        truncated=False,
        elapsed_ms=12.5,
    )

    assert result.columns == columns
    assert result.rows == ((1,), (2,))
    assert result.row_count == EXPECTED_ROW_COUNT
    assert result.truncated is False
    assert result.elapsed_ms == EXPECTED_ELAPSED_MS


def test_chart_spec_defaults_are_safe() -> None:
    spec = ChartSpec(kind="none")

    assert spec.x is None
    assert spec.y == ()
    assert spec.series is None
    assert spec.title == ""
    assert spec.reason == ""
    assert spec.truncated_categories is False


def test_trace_defaults_do_not_share_state() -> None:
    first = Trace()
    second = Trace()

    assert first.phases == ()
    assert first.attempts == ()
    assert first.retrieved_tables == ()
    assert first.tool_calls == 0
    assert first.guardrail_events == ()
    assert first.injection_flags == 0
    assert first.usage == TokenUsage()
    assert first.llm_calls == 0
    assert first.usage is not second.usage


def test_agent_answer_can_represent_a_failure_without_sql() -> None:
    answer = AgentAnswer(
        status=Status.FAILED,
        language=Language.ES,
        text="No pude completar la consulta.",
    )

    assert answer.status is Status.FAILED
    assert answer.language is Language.ES
    assert answer.sql is None
    assert answer.result is None
    assert answer.chart is None
    assert answer.trace == Trace()


def test_attempt_record_and_phase_timing_are_immutable_records() -> None:
    attempt = AttemptRecord(kind="generate", sql="SELECT 1", error_code=None, error_message=None)
    timing = PhaseTiming(phase="GENERATE", elapsed_ms=3.5)

    assert attempt.kind == "generate"
    assert timing.phase == "GENERATE"
    assert timing.elapsed_ms == PHASE_ELAPSED_MS


@pytest.mark.parametrize(
    "model_class",
    [
        TokenUsage,
        ColumnInfo,
        QueryResult,
        ChartSpec,
        AttemptRecord,
        PhaseTiming,
        Trace,
        AgentAnswer,
    ],
)
def test_models_are_frozen_slotted_dataclasses(model_class: type[Any]) -> None:
    assert dataclasses.is_dataclass(model_class)
    assert model_class.__dataclass_params__.frozen
    assert getattr(model_class, "__slots__", None) is not None


def test_frozen_model_rejects_mutation() -> None:
    usage = TokenUsage(prompt=1, completion=2)

    with pytest.raises(dataclasses.FrozenInstanceError):
        usage.prompt = 10  # type: ignore[misc]


def test_error_hierarchy() -> None:
    assert issubclass(GuardrailViolation, SqlAgentError)
    assert issubclass(SqlExecutionError, SqlAgentError)
    assert issubclass(QueryTimeoutError, SqlExecutionError)
    assert issubclass(LLMError, SqlAgentError)
    assert issubclass(LLMProtocolError, LLMError)
    assert issubclass(CassetteMiss, LLMError)
    assert issubclass(WarehouseUnavailable, SqlAgentError)
    assert issubclass(ConfigError, SqlAgentError)
    assert issubclass(SqlAgentError, Exception)


def test_guardrail_code_covers_the_policy_cases_from_d14() -> None:
    expected = {
        "EMPTY_SQL",
        "TOO_LONG",
        "PARSE_ERROR",
        "MULTIPLE_STATEMENTS",
        "NOT_SELECT",
        "FORBIDDEN_NODE",
        "FORBIDDEN_FUNCTION",
        "FORBIDDEN_TABLE",
        "TABLE_FUNCTION",
        "SYSTEM_CATALOG",
        "TOO_DEEP",
        "TOO_COMPLEX",
    }

    assert {code.value for code in GuardrailCode} >= expected


def test_guardrail_violation_carries_code_message_and_detail() -> None:
    violation = GuardrailViolation(
        code=GuardrailCode.FORBIDDEN_TABLE,
        message="table is not allowed",
        detail="tenders_archive",
    )

    assert violation.code is GuardrailCode.FORBIDDEN_TABLE
    assert violation.message == "table is not allowed"
    assert violation.detail == "tenders_archive"
    rendered = str(violation)
    assert "FORBIDDEN_TABLE" in rendered
    assert "table is not allowed" in rendered
    assert "tenders_archive" in rendered


def test_guardrail_violation_without_detail_renders_cleanly() -> None:
    violation = GuardrailViolation(code=GuardrailCode.PARSE_ERROR, message="cannot parse")

    assert violation.detail is None
    assert str(violation) == "PARSE_ERROR: cannot parse"
