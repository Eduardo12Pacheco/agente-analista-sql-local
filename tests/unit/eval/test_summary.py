"""Unit tests for the versioned evaluation summary document (S25)."""

from __future__ import annotations

import json

import pytest

from sqlagent.application.evaluation.metrics import ItemResult
from sqlagent.application.evaluation.summary import (
    SUMMARY_SCHEMA,
    EvalSummary,
    build_summary,
)

pytestmark = pytest.mark.unit


def item_result(item_id: str = "q001") -> ItemResult:
    return ItemResult(
        id=item_id,
        category="aggregation",
        difficulty="easy",
        lang="en",
        expect="answer",
        question="How many tenders are there?",
        status="ok",
        sql="SELECT COUNT(*) AS n FROM tenders",
        gold_sql="SELECT COUNT(*) AS n FROM tenders",
        executed=True,
        ex=True,
        expected_ok=True,
        first_attempt_ex=True,
        valid_sql=True,
        attempts=1,
        failure=None,
        latency_ms=12.5,
        prompt_tokens=100,
        completion_tokens=20,
        retrieved_tables=("tenders",),
        gold_tables=("tenders",),
        guardrail_events=(),
        pair_id=None,
    )


def make_summary(run_id: str = "run-1") -> EvalSummary:
    items = (item_result(),)
    return build_summary(
        benchmark="v1",
        run_id=run_id,
        created_at="2026-11-20T00:00:00+00:00",
        model={"name": "oracle", "digest": "oracle-v1", "backend": "oracle"},
        config={"narrate": False, "retrieval": True},
        environment={"os": "test", "python": "3.12"},
        metrics={"overall": {"ex": 1.0}},
        items=items,
    )


def test_summary_schema_and_json_round_trip() -> None:
    summary = make_summary()
    data = summary.to_dict()
    assert data["schema"] == SUMMARY_SCHEMA == "sqlagent.eval-summary/v1"
    assert data["benchmark"] == "v1"
    assert data["run_id"] == "run-1"
    assert data["model"]["name"] == "oracle"
    assert data["items"][0]["id"] == "q001"
    assert data["items"][0]["ex"] is True
    text = summary.to_json()
    assert json.loads(text) == data
    assert text.endswith("\n")


def test_summary_is_byte_deterministic_for_fixed_metadata() -> None:
    first = make_summary().to_json()
    second = make_summary().to_json()
    assert first == second
    changed = make_summary(run_id="run-2").to_json()
    assert changed != first


def test_results_jsonl_has_one_line_per_item() -> None:
    summary = make_summary()
    lines = summary.results_jsonl().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "q001"
