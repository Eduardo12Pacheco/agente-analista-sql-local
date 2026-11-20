"""Unit tests for execution-accuracy scoring and aggregate metrics (D19/S24)."""

from __future__ import annotations

import math

import pytest

from sqlagent.application.evaluation.benchmark import (
    BenchmarkItem,
    Category,
    Difficulty,
    Expect,
)
from sqlagent.application.evaluation.metrics import (
    ItemResult,
    aggregate_metrics,
    classify_failure,
    nearest_rank_percentile,
    score_item,
    wilson_interval,
)
from sqlagent.domain.models import (
    AgentAnswer,
    AttemptRecord,
    ColumnInfo,
    Language,
    QueryResult,
    Status,
    Trace,
)

pytestmark = pytest.mark.unit


def make_item(
    *,
    item_id: str = "q001",
    category: Category = Category.AGGREGATION,
    difficulty: Difficulty = Difficulty.EASY,
    language: Language = Language.EN,
    expect: Expect = Expect.ANSWER,
    gold_sql: str | None = "SELECT 1 AS n",
    pair_id: str | None = None,
) -> BenchmarkItem:
    return BenchmarkItem(
        id=item_id,
        category=category,
        difficulty=difficulty,
        lang=language,
        question="How many tenders are there?",
        gold_sql=gold_sql,
        pair_id=pair_id,
        expect=expect,
        tags=(),
        notes="",
    )


def make_answer(
    rows: tuple[tuple[object, ...], ...] = ((1,),),
    *,
    status: Status = Status.OK,
    sql: str | None = "SELECT 1 AS n",
    attempts: tuple[AttemptRecord, ...] | None = None,
    guardrails: tuple[str, ...] = (),
) -> AgentAnswer:
    result = None
    if status is Status.OK:
        result = QueryResult(
            columns=(ColumnInfo("n", "BIGINT"),),
            rows=rows,
            row_count=len(rows),
        )
    if attempts is None:
        attempts = () if sql is None else (AttemptRecord(kind="generate", sql=sql),)
    trace = Trace(attempts=attempts, guardrail_events=guardrails)
    return AgentAnswer(
        status=status,
        language=Language.EN,
        text="",
        sql=sql if status is Status.OK else None,
        result=result,
        trace=trace,
    )


def score(
    answer: AgentAnswer,
    *,
    gold_rows: tuple[tuple[object, ...], ...] = ((1,),),
    gold_ordered: bool = False,
    item: object | None = None,
    predicted_tables: tuple[str, ...] = ("tenders",),
    gold_tables: tuple[str, ...] = ("tenders",),
) -> ItemResult:
    return score_item(
        item or make_item(),
        answer,
        gold_rows=gold_rows,
        gold_ordered=gold_ordered,
        gold_tables=gold_tables,
        predicted_tables=predicted_tables,
        latency_ms=10.0,
    )


# -- Wilson interval and percentiles ---------------------------------------
def test_wilson_interval_matches_reference_value() -> None:
    low, high = wilson_interval(36, 72)
    # Canonical Wilson 95% interval with z=1.959964 (the plan quotes 0.389/0.611,
    # which corresponds to z≈1.93; the plan's stated method is 95% Wilson).
    assert low == pytest.approx(0.3875, abs=0.0005)
    assert high == pytest.approx(0.6125, abs=0.0005)
    assert low < 0.5 < high


def test_wilson_interval_edge_cases() -> None:
    assert wilson_interval(0, 0) == (0.0, 0.0)
    low, high = wilson_interval(0, 10)
    assert low == 0.0
    assert high == pytest.approx(0.2775, abs=0.001)
    low, high = wilson_interval(10, 10)
    assert low == pytest.approx(0.7225, abs=0.001)
    assert high == 1.0


def test_nearest_rank_percentile() -> None:
    values = [float(value) for value in range(1, 11)]
    assert nearest_rank_percentile(values, 50) == 5.0
    assert nearest_rank_percentile(values, 95) == 10.0
    assert nearest_rank_percentile(values, 100) == 10.0
    assert nearest_rank_percentile(values, 1) == 1.0
    assert nearest_rank_percentile([], 95) == 0.0


# -- per-item execution accuracy ------------------------------------------
def test_unordered_rows_compare_as_multiset() -> None:
    item = make_item()
    answer = make_answer(((2,), (1,)))
    result = score(answer, gold_rows=((1,), (2,)), item=item)
    assert result.ex is True
    assert result.expected_ok is True
    assert result.failure is None


def test_ordered_rows_compare_as_list() -> None:
    item = make_item(gold_sql="SELECT n FROM tenders ORDER BY n")
    answer = make_answer(((2,), (1,)))
    result = score(answer, gold_rows=((1,), (2,)), gold_ordered=True, item=item)
    assert result.ex is False
    assert result.failure == "wrong_result"


def test_float_tolerance_null_dates_and_extra_columns() -> None:
    item = make_item()
    assert score(make_answer(((0.30000000001,),)), gold_rows=((0.3,),), item=item).ex is True
    assert score(make_answer(((None,),)), gold_rows=((None,),), item=item).ex is True
    assert score(make_answer((("2021-01-04",),)), gold_rows=(("2021-01-04",),), item=item).ex
    extra = make_answer(((1, 2),))
    assert score(extra, gold_rows=((1,),), item=item).ex is False


def test_wrong_row_count_is_not_ex() -> None:
    item = make_item()
    result = score(make_answer(((1,), (2,))), gold_rows=((1,),), item=item)
    assert result.ex is False
    assert result.executed is True


def test_first_attempt_ex_and_repair_tracking() -> None:
    item = make_item()
    failed = AttemptRecord(kind="generate", sql="SELECT bad", error_code="EXECUTION_ERROR")
    repair = AttemptRecord(kind="repair", sql="SELECT 1 AS n")
    answer = make_answer(attempts=(failed, repair))
    result = score(answer, item=item)
    assert result.ex is True
    assert result.first_attempt_ex is False
    assert result.attempts == 2

    clean = score(make_answer(), item=item)
    assert clean.first_attempt_ex is True


# -- non-answerable expectations ------------------------------------------
def test_clarification_expectation() -> None:
    item = make_item(
        category=Category.UNANSWERABLE_AMBIGUOUS, expect=Expect.CLARIFICATION, gold_sql=None
    )
    answer = make_answer(status=Status.CLARIFICATION, sql=None)
    result = score(answer, gold_rows=(), item=item)
    assert result.expected_ok is True
    assert result.ex is None

    refused = make_answer(status=Status.REFUSED, sql=None)
    assert score(refused, gold_rows=(), item=item).expected_ok is False


def test_unanswerable_accepts_clarification_or_refusal() -> None:
    item = make_item(
        category=Category.UNANSWERABLE_AMBIGUOUS, expect=Expect.UNANSWERABLE, gold_sql=None
    )
    for status in (Status.CLARIFICATION, Status.REFUSED):
        answer = make_answer(status=status, sql=None)
        assert score(answer, gold_rows=(), item=item).expected_ok is True
    answered = make_answer(((1,),))
    assert score(answered, gold_rows=(), item=item).expected_ok is False


def test_refusal_expectation() -> None:
    item = make_item(category=Category.ADVERSARIAL_SAFETY, expect=Expect.REFUSAL, gold_sql=None)
    refused = make_answer(status=Status.REFUSED, sql=None)
    assert score(refused, gold_rows=(), item=item).expected_ok is True
    clarified = make_answer(status=Status.CLARIFICATION, sql=None)
    assert score(clarified, gold_rows=(), item=item).expected_ok is False


# -- failure taxonomy ------------------------------------------------------
def test_taxonomy_guardrail_execution_timeout_protocol() -> None:
    item = make_item()
    guardrail = AttemptRecord(kind="generate", sql="DROP TABLE x", error_code="NOT_SELECT")
    assert (
        classify_failure(
            item,
            make_answer(attempts=(guardrail,), guardrails=("NOT_SELECT",)),
            ex=False,
            executed=False,
            predicted_tables=(),
            gold_tables=("tenders",),
        )
        == "guardrail_block"
    )
    execution = AttemptRecord(
        kind="generate",
        sql="SELECT nope",
        error_code="EXECUTION_ERROR",
        error_message="Binder Error",
    )
    assert (
        classify_failure(
            item,
            make_answer(attempts=(execution,)),
            ex=False,
            executed=False,
            predicted_tables=(),
            gold_tables=("tenders",),
        )
        == "execution_error"
    )
    timeout = AttemptRecord(
        kind="generate",
        sql="SELECT 1",
        error_code="EXECUTION_ERROR",
        error_message="query timeout exceeded",
    )
    assert (
        classify_failure(
            item,
            make_answer(attempts=(timeout,)),
            ex=False,
            executed=False,
            predicted_tables=(),
            gold_tables=("tenders",),
        )
        == "timeout"
    )
    failed = make_answer(status=Status.FAILED, sql=None, attempts=())
    assert (
        classify_failure(
            item,
            failed,
            ex=False,
            executed=False,
            predicted_tables=(),
            gold_tables=("tenders",),
        )
        == "protocol_error"
    )


def test_taxonomy_wrong_tables_refusal_and_wrong_result() -> None:
    item = make_item()
    answer = make_answer()
    assert (
        classify_failure(
            item,
            answer,
            ex=False,
            executed=True,
            predicted_tables=("suppliers",),
            gold_tables=("tenders",),
        )
        == "wrong_tables"
    )
    refused = make_answer(status=Status.REFUSED, sql=None)
    assert (
        classify_failure(
            item,
            refused,
            ex=False,
            executed=False,
            predicted_tables=(),
            gold_tables=("tenders",),
        )
        == "refusal_mismatch"
    )
    assert (
        classify_failure(
            item,
            answer,
            ex=False,
            executed=True,
            predicted_tables=("tenders",),
            gold_tables=("tenders",),
        )
        == "wrong_result"
    )


# -- aggregation -----------------------------------------------------------
def _result(
    item_id: str,
    *,
    category: Category,
    expect: Expect,
    ex: bool | None,
    expected_ok: bool,
    first: bool | None = True,
    attempts: int = 1,
    failure: str | None = None,
    latency_ms: float = 10.0,
    pair_id: str | None = None,
    retrieved: tuple[str, ...] = ("tenders",),
    gold_tables: tuple[str, ...] = ("tenders",),
) -> ItemResult:
    return ItemResult(
        id=item_id,
        category=category.value,
        difficulty=Difficulty.EASY.value,
        lang=Language.EN.value,
        expect=expect.value,
        question="q",
        status=Status.OK.value if ex else Status.FAILED.value,
        sql="SELECT 1 AS n",
        gold_sql="SELECT 1 AS n" if expect is Expect.ANSWER else None,
        executed=ex is not None and (ex or failure is not None),
        ex=ex,
        expected_ok=expected_ok,
        first_attempt_ex=first,
        valid_sql=ex is not None,
        attempts=attempts,
        failure=failure,
        latency_ms=latency_ms,
        prompt_tokens=10,
        completion_tokens=5,
        retrieved_tables=retrieved,
        gold_tables=gold_tables,
        guardrail_events=(),
        pair_id=pair_id,
    )


def test_aggregate_metrics_overall_breakdowns_and_taxonomy() -> None:
    items = (
        _result(
            "q001", category=Category.AGGREGATION, expect=Expect.ANSWER, ex=True, expected_ok=True
        ),
        _result(
            "q002",
            category=Category.AGGREGATION,
            expect=Expect.ANSWER,
            ex=False,
            expected_ok=False,
            first=False,
            failure="wrong_result",
            latency_ms=30.0,
        ),
        _result(
            "q003",
            category=Category.ADVERSARIAL_SAFETY,
            expect=Expect.REFUSAL,
            ex=None,
            expected_ok=True,
            first=None,
            retrieved=(),
            gold_tables=(),
        ),
        _result(
            "q004",
            category=Category.UNANSWERABLE_AMBIGUOUS,
            expect=Expect.UNANSWERABLE,
            ex=None,
            expected_ok=False,
            first=None,
            failure="refusal_mismatch",
            retrieved=(),
            gold_tables=(),
        ),
    )
    metrics = aggregate_metrics(items)
    overall = metrics["overall"]
    assert overall["n"] == 2
    assert overall["included"] == 4
    assert overall["ex"] == pytest.approx(0.5)
    assert overall["ex_ci_low"] < 0.5 < overall["ex_ci_high"]
    assert overall["valid_sql_rate"] == pytest.approx(1.0)
    assert overall["first_attempt_ex"] == pytest.approx(0.5)
    assert overall["repair_uplift"] == pytest.approx(0.0)
    assert overall["refusal_acc"] == pytest.approx(1.0)
    assert overall["unanswerable_acc"] == pytest.approx(0.0)
    assert overall["clarification_acc"] == pytest.approx(1.0)  # no clarification items
    assert overall["retrieval_table_recall"] == pytest.approx(1.0)
    assert overall["latency_ms"]["mean"] == pytest.approx(15.0)
    assert overall["tokens"]["prompt_per_question"] == pytest.approx(10.0)
    categories = metrics["by_category"]
    assert categories["aggregation"]["ex"] == pytest.approx(0.5)
    assert categories["adversarial_safety"]["ex"] == pytest.approx(1.0)
    assert categories["unanswerable_ambiguous"]["ex"] == pytest.approx(0.0)
    assert metrics["failure_taxonomy"] == {"wrong_result": 1, "refusal_mismatch": 1}
    assert set(metrics["by_language"]) == {"en"}
    assert set(metrics["by_difficulty"]) == {"easy"}


def test_pair_consistency_and_retrieval_recall() -> None:
    items = (
        _result(
            "q001",
            category=Category.JOIN,
            expect=Expect.ANSWER,
            ex=True,
            expected_ok=True,
            pair_id="p01",
            retrieved=("tenders",),
            gold_tables=("tenders", "buyers"),
        ),
        _result(
            "q002",
            category=Category.JOIN,
            expect=Expect.ANSWER,
            ex=True,
            expected_ok=True,
            pair_id="p01",
            retrieved=("tenders", "buyers"),
            gold_tables=("tenders", "buyers"),
        ),
        _result(
            "q003",
            category=Category.JOIN,
            expect=Expect.ANSWER,
            ex=False,
            expected_ok=False,
            first=False,
            failure="wrong_result",
            pair_id="p02",
            retrieved=("awards",),
            gold_tables=("tenders",),
        ),
        _result(
            "q004",
            category=Category.JOIN,
            expect=Expect.ANSWER,
            ex=False,
            expected_ok=False,
            first=False,
            failure="wrong_result",
            pair_id="p02",
            retrieved=(),
            gold_tables=("tenders",),
        ),
    )
    metrics = aggregate_metrics(items)
    # p01 has both correct, p02 has neither: only p01 counts for consistency.
    assert metrics["overall"]["pair_consistency"] == pytest.approx(1.0)
    # mean recall: 1/2, 1, 0/1, 0/1 => 0.375
    assert metrics["overall"]["retrieval_table_recall"] == pytest.approx(0.375)


def test_expectation_accuracy_handles_no_pairs() -> None:
    item = _result(
        "q001", category=Category.AGGREGATION, expect=Expect.ANSWER, ex=True, expected_ok=True
    )
    metrics = aggregate_metrics([item])
    assert metrics["overall"]["pair_consistency"] == pytest.approx(1.0)
    assert math.isclose(metrics["overall"]["clarification_acc"], 1.0)
