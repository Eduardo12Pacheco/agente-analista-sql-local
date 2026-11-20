"""Versioned evaluation summary document (``sqlagent.eval-summary/v1``, S25).

The summary is the single source of truth for reports, the regression gate and
the README metrics table.  It is built from immutable per-item results and plain
dictionaries so the JSON is deterministic: two runs with the same run id,
timestamp and clock produce byte-identical documents.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlagent import __version__
from sqlagent.application.evaluation.metrics import ItemResult

SUMMARY_SCHEMA = "sqlagent.eval-summary/v1"


@dataclass(frozen=True, slots=True)
class EvalSummary:
    """One reproducible evaluation report document."""

    benchmark: str
    run_id: str
    created_at: str
    model: Mapping[str, Any]
    config: Mapping[str, Any]
    environment: Mapping[str, Any]
    metrics: Mapping[str, Any]
    items: tuple[ItemResult, ...]
    schema: str = SUMMARY_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe document in stable key order."""

        return {
            "schema": self.schema,
            "benchmark": self.benchmark,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "model": dict(self.model),
            "config": dict(self.config),
            "environment": dict(self.environment),
            "metrics": dict(self.metrics),
            "items": [item.to_dict() for item in self.items],
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Serialise with a trailing newline, as written to ``summary.json``."""

        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent) + "\n"

    def results_jsonl(self) -> str:
        """Serialise one compact JSON object per item."""

        lines = [json.dumps(item.to_dict(), ensure_ascii=False) for item in self.items]
        return "\n".join(lines) + ("\n" if lines else "")


def build_summary(  # noqa: PLR0913 - explicit document sections
    *,
    benchmark: str,
    run_id: str,
    created_at: str,
    model: Mapping[str, Any],
    config: Mapping[str, Any],
    environment: Mapping[str, Any],
    metrics: Mapping[str, Any],
    items: Sequence[ItemResult],
) -> EvalSummary:
    """Build a summary from already-computed pieces (pure, deterministic)."""

    return EvalSummary(
        benchmark=benchmark,
        run_id=run_id,
        created_at=created_at,
        model=dict(model),
        config=dict(config),
        environment=dict(environment),
        metrics=dict(metrics),
        items=tuple(items),
    )


def _gpu_description() -> str | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - fixed executable and arguments
            [
                executable,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    line = completed.stdout.strip().splitlines()[0].strip() if completed.stdout.strip() else ""
    return line or None


def collect_environment(*, warehouse_manifest_sha256: str) -> dict[str, Any]:
    """Collect the D34 environment line without reading row data or secrets."""

    return {
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "sqlagent": __version__,
        "gpu": _gpu_description(),
        "warehouse_manifest_sha256": warehouse_manifest_sha256,
    }


__all__ = [
    "SUMMARY_SCHEMA",
    "EvalSummary",
    "build_summary",
    "collect_environment",
]
