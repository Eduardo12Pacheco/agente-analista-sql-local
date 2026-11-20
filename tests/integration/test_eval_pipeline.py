"""Integration tests for the T9 evaluation pipeline (S24/S25/S26/S40)."""

from __future__ import annotations

import re
import time

import pytest
from typer.testing import CliRunner

from sqlagent.adapters.benchmark.yaml_repository import YamlBenchmarkRepository
from sqlagent.adapters.cli import main as main_module
from sqlagent.adapters.cli.main import app
from sqlagent.adapters.reporting.markdown import MarkdownHtmlReportWriter
from sqlagent.application.use_cases.evaluate import EvaluationRequest, RunEvaluation
from sqlagent.bootstrap import build_agent, build_warehouse
from sqlagent.config import Settings
from sqlagent.domain.sql_policy import SqlPolicy
from tests.support.oracle_llm import OracleLLM
from tests.support.sabotaged_llm import SabotagedLLM

pytestmark = pytest.mark.integration

ALLOWED_EXTERNAL_URLS = {
    "https://datosabiertos.compraspublicas.gob.ec",
    "https://creativecommons.org/licenses/by/3.0/ec/",
}


class FixedClock:
    """Deterministic monotonic clock: each call advances one second."""

    def __init__(self) -> None:
        self._ticks = 0

    def __call__(self) -> float:
        self._ticks += 1
        return float(self._ticks)


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    data_dir = tmp_path_factory.mktemp("eval-data")
    return Settings(data_dir=data_dir, llm_backend="replay", query_timeout_s=20)


@pytest.fixture(scope="module")
def warehouse(settings: Settings):
    instance = build_warehouse(settings)
    yield instance
    instance.close()


@pytest.fixture(scope="module")
def benchmark():
    return YamlBenchmarkRepository().load("v1")


def _use_case(
    benchmark,
    agent,
    llm,
    warehouse,
    settings: Settings,
    *,
    clock=None,
) -> RunEvaluation:
    policy = SqlPolicy(
        catalog_tables=warehouse.catalog().table_names(),
        max_rows=settings.max_rows,
    )
    return RunEvaluation(
        benchmark=benchmark,
        agent=agent,
        llm=llm,
        warehouse=warehouse,
        policy=policy,
        writer=MarkdownHtmlReportWriter(),
        settings=settings,
        clock=clock or FixedClock(),
    )


@pytest.fixture(scope="module")
def oracle_run(benchmark, warehouse, settings, tmp_path_factory: pytest.TempPathFactory):
    oracle = OracleLLM(benchmark)
    agent = build_agent(settings, llm=oracle, warehouse=warehouse, narrate=False)
    out_dir = tmp_path_factory.mktemp("oracle-run")
    use_case = _use_case(benchmark, agent, oracle, warehouse, settings)
    started = time.monotonic()
    outcome = use_case.execute(
        EvaluationRequest(
            out_dir=out_dir,
            run_id="20261120T000000Z-oracle",
            created_at="2026-11-20T00:00:00+00:00",
        )
    )
    elapsed = time.monotonic() - started
    return outcome, elapsed, oracle


def test_oracle_full_run_scores_perfect_and_writes_reports(oracle_run) -> None:
    outcome, elapsed, oracle = oracle_run
    summary = outcome.summary
    metrics = summary.metrics
    assert len(outcome.results) == 72
    assert len(oracle.requests) == 72  # one GENERATE call per item, narration disabled
    assert metrics["overall"]["n"] == 60
    assert metrics["overall"]["ex"] == pytest.approx(1.0)
    assert metrics["overall"]["ex_ci_low"] == pytest.approx(0.94, abs=0.01)
    assert metrics["overall"]["valid_sql_rate"] == pytest.approx(1.0)
    assert metrics["overall"]["first_attempt_ex"] == pytest.approx(1.0)
    assert metrics["overall"]["repair_uplift"] == pytest.approx(0.0)
    assert metrics["overall"]["refusal_acc"] == pytest.approx(1.0)
    assert metrics["overall"]["clarification_acc"] == pytest.approx(1.0)
    assert metrics["overall"]["unanswerable_acc"] == pytest.approx(1.0)
    assert metrics["failure_taxonomy"] == {}
    assert elapsed < 120.0

    files = {path.name for path in outcome.out_dir.iterdir()}
    assert files == {"summary.json", "results.jsonl", "report.md", "report.html"}
    html = (outcome.out_dir / "report.html").read_text(encoding="utf-8")
    assert "<svg" in html
    urls = set()
    for match in re.findall(r"https?://[^\s\"'<>)]+", html):
        urls.add(match.rstrip(".,"))
    assert urls <= ALLOWED_EXTERNAL_URLS
    assert "sqlagent.eval-summary/v1" in (outcome.out_dir / "summary.json").read_text(
        encoding="utf-8"
    )
    assert len((outcome.out_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()) == 72


def test_oracle_run_is_deterministic_with_fixed_clock(
    benchmark, warehouse, settings, oracle_run, tmp_path
) -> None:
    outcome, _, _ = oracle_run
    oracle = OracleLLM(benchmark)
    agent = build_agent(settings, llm=oracle, warehouse=warehouse, narrate=False)
    use_case = _use_case(benchmark, agent, oracle, warehouse, settings)
    second = use_case.execute(
        EvaluationRequest(
            out_dir=tmp_path / "second",
            run_id=outcome.summary.run_id,
            created_at=outcome.summary.created_at,
        )
    )
    assert second.summary.to_json() == outcome.summary.to_json()


def test_no_retrieval_ablation_sends_all_tables(benchmark, warehouse, settings, tmp_path) -> None:
    oracle = OracleLLM(benchmark)
    agent = build_agent(settings, llm=oracle, warehouse=warehouse, narrate=False, retrieve=False)
    use_case = _use_case(benchmark, agent, oracle, warehouse, settings)
    outcome = use_case.execute(
        EvaluationRequest(
            out_dir=tmp_path / "ablation",
            run_id="ablation",
            created_at="2026-11-20T00:00:00+00:00",
            limit=1,
            retrieval=False,
        )
    )
    assert outcome.summary.config["retrieval"] is False
    assert outcome.results[0].retrieved_tables == (
        "buyers",
        "suppliers",
        "tenders",
        "awards",
        "contracts",
        "tender_items",
    )


def test_sabotaged_gate_exits_one_and_prints_regressions(
    benchmark, warehouse, settings, oracle_run, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outcome, _, _ = oracle_run
    baseline = tmp_path / "baseline.json"
    baseline.write_text(outcome.summary.to_json(), encoding="utf-8")

    sabotaged = SabotagedLLM(benchmark, "no_repair")
    sabotaged_agent = build_agent(
        settings,
        llm=sabotaged,
        warehouse=warehouse,
        narrate=False,
    )
    monkeypatch.setattr(main_module, "build_llm", lambda *args, **kwargs: sabotaged)
    monkeypatch.setattr(main_module, "build_agent", lambda settings, **kwargs: sabotaged_agent)

    result = CliRunner().invoke(
        app,
        [
            "eval",
            "--llm",
            "ollama",
            "--compare",
            str(baseline),
            "--out",
            str(tmp_path / "sabotaged"),
            "--limit",
            "12",
            "--category",
            "aggregation",
            "--category",
            "filtering",
            "--category",
            "join",
        ],
    )
    output = result.stdout + result.stderr
    assert result.exit_code == 1
    assert "REGRESSION overall.ex" in output
    assert "by_category.aggregation.ex" in output


def test_eval_cli_help_lists_every_d25_option() -> None:
    result = CliRunner().invoke(app, ["eval", "--help"])
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    for option in (
        "--llm",
        "--model",
        "--benchmark",
        "--category",
        "--limit",
        "--record",
        "--out",
        "--compare",
        "--max-drop",
        "--with-narration",
        "--max-repairs",
        "--no-retrieval",
    ):
        assert option in plain


def test_eval_replay_without_recordings_exits_four(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SQLAGENT_DATA_DIR", str(tmp_path / "data"))
    result = CliRunner().invoke(
        app,
        [
            "eval",
            "--llm",
            "replay",
            "--model",
            "unrecorded-model:1b",
            "--limit",
            "3",
            "--out",
            str(tmp_path / "replay"),
        ],
    )
    output = result.stdout + result.stderr
    assert result.exit_code == 4
    assert "--record" in output


def test_gate_compare_rejects_missing_baseline(
    benchmark, warehouse, settings, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oracle = OracleLLM(benchmark)
    agent = build_agent(settings, llm=oracle, warehouse=warehouse, narrate=False)
    monkeypatch.setattr(main_module, "build_llm", lambda *args, **kwargs: oracle)
    monkeypatch.setattr(main_module, "build_agent", lambda settings, **kwargs: agent)
    result = CliRunner().invoke(
        app,
        [
            "eval",
            "--llm",
            "ollama",
            "--limit",
            "1",
            "--compare",
            str(tmp_path / "missing.json"),
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 2
    assert "baseline" in (result.stdout + result.stderr).lower()
