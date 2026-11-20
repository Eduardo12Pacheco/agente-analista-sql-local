"""Recorded-output freshness test (D18/T12): replay all 72 questions offline.

The committed cassette is the regression baseline for the prompt freeze: any
change to prompts, few-shots, semantic layer, retrieval parameters, sanitiser
rendering or the warehouse Parquet invalidates it.  This test replays the whole
benchmark through the real agent and fails with ``CassetteMiss`` when a request
has no recorded answer, or when the replayed run does not reproduce the
committed baseline execution accuracy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sqlagent.adapters.benchmark.yaml_repository import YamlBenchmarkRepository
from sqlagent.adapters.llm.cassette import ReplayLLM
from sqlagent.adapters.reporting.markdown import MarkdownHtmlReportWriter
from sqlagent.application.evaluation.runner import TrackingLLM
from sqlagent.application.use_cases.evaluate import EvaluationRequest, RunEvaluation
from sqlagent.bootstrap import build_agent, build_warehouse, default_cassette_path
from sqlagent.config import DEFAULT_MODEL, Settings
from sqlagent.domain.errors import CassetteMiss
from sqlagent.domain.sql_policy import SqlPolicy

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / "eval" / "baseline.json"


@pytest.fixture(scope="module")
def baseline() -> dict[str, object]:
    assert BASELINE_PATH.is_file(), (
        "eval/baseline.json is missing; T12 must commit the recorded default-model run"
    )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def settings(baseline: dict[str, object], tmp_path_factory: pytest.TempPathFactory) -> Settings:
    model = baseline["model"]
    assert isinstance(model, dict)
    data_dir = tmp_path_factory.mktemp("recordings-fresh-data")
    return Settings(
        data_dir=data_dir,
        llm_backend="replay",
        model=str(model["name"]),
    )


@pytest.fixture(scope="module")
def warehouse(settings: Settings):
    instance = build_warehouse(settings)
    yield instance
    instance.close()


def test_default_model_is_the_measured_best_model(baseline: dict[str, object]) -> None:
    model = baseline["model"]
    assert isinstance(model, dict)
    assert model["name"] == DEFAULT_MODEL, (
        "DEFAULT_MODEL must match the model whose run produced eval/baseline.json"
    )


def test_cassette_file_is_committed_for_default_model(settings: Settings) -> None:
    cassette = default_cassette_path(settings.model)
    assert cassette.is_file(), f"missing recorded cassette {cassette}"
    assert cassette.stat().st_size <= 3 * 1024 * 1024, "cassette must stay under 3 MB (T12)"


def test_replay_reproduces_baseline_without_cassette_miss(
    baseline: dict[str, object],
    settings: Settings,
    warehouse,
    tmp_path: Path,
) -> None:
    repository = YamlBenchmarkRepository()
    benchmark = repository.load("v1")

    replay = TrackingLLM(ReplayLLM(default_cassette_path(settings.model)))
    agent = build_agent(settings, llm=replay, warehouse=warehouse, narrate=False)
    policy = SqlPolicy(
        catalog_tables=warehouse.catalog().table_names(),
        max_rows=settings.max_rows,
    )
    outcome = RunEvaluation(
        benchmark=benchmark,
        agent=agent,
        llm=replay,
        warehouse=warehouse,
        policy=policy,
        writer=MarkdownHtmlReportWriter(),
        settings=settings,
    ).execute(
        EvaluationRequest(
            out_dir=tmp_path / "replay",
            run_id=str(baseline["run_id"]),
            created_at=str(baseline["created_at"]),
        )
    )

    if replay.last_error is not None:
        assert isinstance(replay.last_error, CassetteMiss), replay.last_error
        raise replay.last_error

    assert len(outcome.results) == 72
    expected = baseline["metrics"]
    assert isinstance(expected, dict)
    expected_overall = expected["overall"]
    actual_overall = outcome.summary.metrics["overall"]
    assert actual_overall["ex"] == pytest.approx(expected_overall["ex"])
    assert actual_overall["valid_sql_rate"] == pytest.approx(expected_overall["valid_sql_rate"])
    assert actual_overall["refusal_acc"] == pytest.approx(expected_overall["refusal_acc"])
