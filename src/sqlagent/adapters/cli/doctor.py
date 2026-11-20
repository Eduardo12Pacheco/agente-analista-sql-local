"""Environment diagnostics for ``sqlagent doctor`` (S39).

The warehouse is the only hard requirement: Ollama is optional, so a missing
backend is reported with the exact pull/start commands while the command still
exits 0.  ``--offline`` never touches the network and reports whether the
committed replay cassette makes demo mode available.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sqlagent.adapters.llm.ollama import OllamaLLM
from sqlagent.adapters.warehouse.etl import BUNDLE_DIR, verify_bundle
from sqlagent.bootstrap import build_warehouse, default_cassette_path
from sqlagent.config import Settings
from sqlagent.domain.errors import SqlAgentError


@dataclass(frozen=True, slots=True)
class Check:
    """One doctor check line."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Structured doctor result rendered by the CLI and exercised by tests."""

    checks: tuple[Check, ...]
    actions: tuple[str, ...]
    warehouse_ok: bool
    demo_available: bool
    warehouse_path: Path | None
    exit_code: int


def _ollama_actions(model: str) -> tuple[str, ...]:
    return (
        f"native Ollama: ollama pull {model}",
        f"Docker: scripts/ollama-docker.sh up && scripts/ollama-docker.sh pull {model}",
        "Docker endpoint: SQLAGENT_OLLAMA_URL=http://127.0.0.1:11435",
    )


def _gpu_check() -> Check:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return Check("GPU", True, "nvidia-smi not found; the CPU fallback works")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed nvidia-smi argv
            [executable, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Check("GPU", True, f"nvidia-smi unavailable: {exc}")
    output = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not output:
        return Check("GPU", True, "nvidia-smi present but returned no device details")
    return Check("GPU", True, output[0])


def _warehouse_checks(settings: Settings) -> tuple[Check, Path | None, bool]:
    try:
        report = verify_bundle(BUNDLE_DIR)
        if not report.ok:
            detail = "; ".join(report.errors[:3]) or "bundle verification failed"
            return (Check("warehouse", False, f"verification failed: {detail}"), None, False)
        warehouse = build_warehouse(settings)
        try:
            info = warehouse.info()
            rows = sum(info.tables.values())
            tables = len(info.tables)
        finally:
            warehouse.close()
    except (SqlAgentError, OSError) as exc:
        return (Check("warehouse", False, f"broken: {exc}"), None, False)
    detail = f"OK ({tables} tables, {rows:,} rows) at {info.path}"
    return (Check("warehouse", True, detail), info.path, True)


def run_doctor(settings: Settings | None = None, *, offline: bool = False) -> DoctorReport:
    """Run every check and return a report; never raises for environment problems."""

    settings = settings or Settings()
    checks: list[Check] = [
        Check(
            "environment",
            True,
            f"Python {platform.python_version()} on {platform.platform()}",
        )
    ]
    warehouse_check, warehouse_path, warehouse_ok = _warehouse_checks(settings)
    checks.append(warehouse_check)

    cassette = default_cassette_path(settings.model)
    demo_available = cassette.is_file()
    demo_detail = (
        f"replay cassette available at {cassette}"
        if demo_available
        else "no replay cassette bundled yet; demo mode becomes available after T12"
    )
    checks.append(Check("demo", True, demo_detail))

    actions: list[str] = []
    if offline:
        checks.append(Check("Ollama", True, "skipped (--offline)"))
        actions.extend(_ollama_actions(settings.model))
    else:
        try:
            llm = OllamaLLM(settings)
        except SqlAgentError as exc:
            checks.append(Check("Ollama", False, f"configuration rejected: {exc}"))
            actions.extend(_ollama_actions(settings.model))
        else:
            try:
                probe = llm.probe()
            finally:
                llm.close()
            if not probe.reachable:
                checks.append(Check("Ollama", False, f"not reachable at {settings.ollama_url}"))
                actions.extend(_ollama_actions(settings.model))
            else:
                checks.append(
                    Check("Ollama", True, f"reachable (version {probe.version or 'unknown'})")
                )
                if probe.model_present:
                    checks.append(Check("model", True, f"{settings.model} is installed"))
                else:
                    checks.append(Check("model", False, f"{settings.model} is not installed"))
                    actions.extend(_ollama_actions(settings.model))

    checks.append(_gpu_check())
    if demo_available:
        actions.append('offline demo: SQLAGENT_LLM_BACKEND=replay sqlagent ask "..."')

    return DoctorReport(
        checks=tuple(checks),
        actions=tuple(actions),
        warehouse_ok=warehouse_ok,
        demo_available=demo_available,
        warehouse_path=warehouse_path,
        exit_code=0 if warehouse_ok else 3,
    )
