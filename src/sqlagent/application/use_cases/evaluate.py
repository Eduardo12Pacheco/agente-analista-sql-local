"""``RunEvaluation`` use case: run, score, persist and gate one benchmark run (T9).

The use case is the application-level orchestration; the runner owns SQL
execution and the report writer owns serialisation.  Everything the CLI needs is
returned in :class:`EvaluationOutcome`, which keeps the CLI a thin adapter.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlagent.application.agent.machine import AnalystAgent
from sqlagent.application.agent.prompts import PROMPT_VERSION
from sqlagent.application.evaluation.benchmark import (
    BENCHMARK_VERSION,
    Benchmark,
    BenchmarkItem,
    BenchmarkLock,
    Category,
)
from sqlagent.application.evaluation.gate import GateReport, compare_summaries
from sqlagent.application.evaluation.metrics import ItemResult, aggregate_metrics
from sqlagent.application.evaluation.runner import EvaluationRunner
from sqlagent.application.evaluation.summary import (
    EvalSummary,
    build_summary,
    collect_environment,
)
from sqlagent.application.ports import LLMPort, ReportWriter, WarehousePort
from sqlagent.config import Settings
from sqlagent.domain.errors import ConfigError
from sqlagent.domain.sql_policy import SqlPolicy

GATE_SCHEMA = "sqlagent.eval-gate/v1"
LOCK_FILENAME = "benchmark.lock.json"
QUESTIONS_FILENAME = "questions.yaml"


def model_slug(model: str) -> str:
    """Return the filesystem-safe model slug used in run ids and cassettes."""

    return model.replace(":", "-").replace("/", "-")


@dataclass(frozen=True, slots=True)
class EvaluationRequest:
    """Options for one run (the CLI maps D25 flags onto these fields)."""

    categories: tuple[Category, ...] = ()
    limit: int | None = None
    with_narration: bool = False
    retrieval: bool = True
    out_dir: Path | None = None
    run_id: str | None = None
    created_at: str | None = None
    compare: Path | None = None
    max_drop: float = 0.0


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    """Result of a run: summary, per-item results, artifacts and optional gate."""

    summary: EvalSummary
    results: tuple[ItemResult, ...]
    out_dir: Path
    gate: GateReport | None = None


@dataclass(frozen=True, slots=True)
class _RunMetadata:
    run_id: str
    created_at: str


def verify_benchmark_lock(benchmark_dir: Path, version: str, manifest_path: Path) -> None:
    """Fail with ``ConfigError`` when the benchmark lock is stale (D20 exit 2)."""

    lock_path = Path(benchmark_dir) / version / LOCK_FILENAME
    questions_path = Path(benchmark_dir) / version / QUESTIONS_FILENAME
    try:
        lock = BenchmarkLock.model_validate(json.loads(lock_path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise ConfigError(f"cannot read benchmark lock {lock_path}: {exc}") from exc
    except ValueError as exc:
        raise ConfigError(f"invalid benchmark lock {lock_path}: {exc}") from exc
    try:
        questions_hash = hashlib.sha256(questions_path.read_bytes()).hexdigest()
        manifest_hash = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    except OSError as exc:
        raise ConfigError(f"cannot hash benchmark inputs: {exc}") from exc
    if questions_hash != lock.questions_sha256 or manifest_hash != lock.warehouse_manifest_sha256:
        raise ConfigError(
            "benchmark/baseline drift: benchmark.lock.json does not match "
            "questions.yaml or the warehouse MANIFEST.json; re-run "
            "`uv run python scripts/lock_benchmark.py`"
        )


class RunEvaluation:
    """Run benchmark items, write the four artifacts and optionally gate."""

    def __init__(  # noqa: PLR0913 - explicit dependency injection
        self,
        *,
        benchmark: Benchmark,
        agent: AnalystAgent,
        llm: LLMPort,
        warehouse: WarehousePort,
        policy: SqlPolicy,
        writer: ReportWriter,
        settings: Settings,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._benchmark = benchmark
        self._agent = agent
        self._llm = llm
        self._warehouse = warehouse
        self._policy = policy
        self._writer = writer
        self._settings = settings
        self._runner = (
            EvaluationRunner(agent, warehouse, policy, clock=clock)
            if clock is not None
            else EvaluationRunner(agent, warehouse, policy)
        )

    def execute(self, request: EvaluationRequest) -> EvaluationOutcome:
        """Run the selected items and persist all artifacts."""

        if request.limit is not None and request.limit < 1:
            raise ConfigError("--limit must be a positive integer")
        metadata = self._metadata(request)
        items = self._select(request)
        results = self._runner.run(items)
        metrics = aggregate_metrics(results)
        info = self._warehouse.info()
        model = self._model_info()
        config = self._config(request)
        summary = build_summary(
            benchmark=self._benchmark.version,
            run_id=metadata.run_id,
            created_at=metadata.created_at,
            model=model,
            config=config,
            environment=collect_environment(warehouse_manifest_sha256=info.manifest_sha256),
            metrics=metrics,
            items=results,
        )
        out_dir = (
            Path(request.out_dir)
            if request.out_dir is not None
            else (Path("eval/reports") / metadata.run_id)
        )
        self._writer.write(summary, results, out_dir)
        gate = None
        if request.compare is not None:
            gate = compare_summaries(
                _load_baseline(request.compare),
                summary.to_dict(),
                max_drop=request.max_drop,
            )
        return EvaluationOutcome(
            summary=summary,
            results=results,
            out_dir=out_dir,
            gate=gate,
        )

    def _metadata(self, request: EvaluationRequest) -> _RunMetadata:
        now = datetime.now(tz=UTC)
        model = self._llm.describe().model or self._settings.model
        run_id = request.run_id or f"{now:%Y%m%dT%H%M%SZ}-{model_slug(model)}"
        created_at = request.created_at or now.isoformat(timespec="seconds")
        return _RunMetadata(run_id=run_id, created_at=created_at)

    def _select(self, request: EvaluationRequest) -> tuple[BenchmarkItem, ...]:
        items = self._benchmark.items
        if request.categories:
            selected = set(request.categories)
            items = tuple(item for item in items if item.category in selected)
        if request.limit is not None:
            items = items[: request.limit]
        if not items:
            raise ConfigError("the selected benchmark filter matched no items")
        return items

    def _model_info(self) -> dict[str, Any]:
        info = self._llm.describe()
        return {
            "name": info.model or self._settings.model,
            "digest": info.digest,
            "backend": info.backend,
        }

    def _config(self, request: EvaluationRequest) -> dict[str, Any]:
        return {
            "benchmark_version": self._benchmark.version,
            "prompt_version": PROMPT_VERSION,
            "categories": [category.value for category in request.categories],
            "limit": request.limit,
            "narrate": request.with_narration,
            "retrieval": request.retrieval,
            "max_repairs": self._settings.max_repairs,
            "max_rows": self._settings.max_rows,
            "temperature": self._settings.temperature,
            "seed": self._settings.seed,
            "num_ctx": self._settings.num_ctx,
            "num_predict": self._settings.num_predict,
            "llm_backend": self._settings.llm_backend,
        }


def _load_baseline(path: Path) -> Mapping[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read baseline {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"baseline {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ConfigError(f"baseline {path} must contain a JSON object")
    return data


__all__ = [
    "BENCHMARK_VERSION",
    "GATE_SCHEMA",
    "EvaluationOutcome",
    "EvaluationRequest",
    "RunEvaluation",
    "model_slug",
    "verify_benchmark_lock",
]
