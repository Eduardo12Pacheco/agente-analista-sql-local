"""Delivery workflows stay valid, pinned and complete (S36/S37, T13)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_PATH = ROOT / ".github" / "workflows" / "release.yml"
ACTION_REF = re.compile(r"^[^@\s]+@v\d+(?:\.\d+){0,2}$")

pytestmark = pytest.mark.unit


def _load(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"missing workflow: {path}"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _iter_values(node: Any) -> list[Any]:
    if isinstance(node, dict):
        values: list[Any] = []
        for value in node.values():
            values.extend(_iter_values(value))
        return values
    if isinstance(node, list):
        values = []
        for value in node:
            values.extend(_iter_values(value))
        return values
    return [node]


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML resolves the bare ``on`` key to boolean True (YAML 1.1).
    raw = workflow.get("on", workflow.get(True))
    assert isinstance(raw, dict), "workflow must declare an `on:` mapping"
    return raw


def _matrices(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    matrices: list[dict[str, Any]] = []
    jobs = workflow.get("jobs", {})
    assert isinstance(jobs, dict)
    for job in jobs.values():
        strategy = job.get("strategy", {}) if isinstance(job, dict) else {}
        matrix = strategy.get("matrix", {}) if isinstance(strategy, dict) else {}
        if isinstance(matrix, dict):
            matrices.append(matrix)
    return matrices


def _matrix_oses(workflow: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for matrix in _matrices(workflow):
        include = matrix.get("include", [])
        if isinstance(include, list):
            names.update(
                entry["os"] for entry in include if isinstance(entry, dict) and "os" in entry
            )
        oses = matrix.get("os", [])
        if isinstance(oses, list):
            names.update(oses)
    return names


def test_ci_declares_required_jobs() -> None:
    workflow = _load(CI_PATH)
    jobs = workflow["jobs"]

    assert {"lint", "test", "security", "e2e", "eval-gate", "installer-smoke"} <= set(jobs)
    for name, job in jobs.items():
        assert "runs-on" in job, f"job {name} has no runner"


def test_release_declares_build_smoke_and_release_jobs() -> None:
    workflow = _load(RELEASE_PATH)
    jobs = workflow["jobs"]

    assert {"build", "smoke", "release"} <= set(jobs)
    release = jobs["release"]
    assert release["needs"] == ["build", "smoke"]
    assert release["permissions"] == {"contents": "write"}


def test_workflows_pin_every_action_to_a_version_tag() -> None:
    for path in (CI_PATH, RELEASE_PATH):
        workflow = _load(path)
        uses = [value for value in _iter_values(workflow) if isinstance(value, str)]
        refs = [value for value in uses if "/" in value and not value.startswith(("run:", "./"))]
        action_refs = [
            value
            for value in refs
            if value.startswith(("actions/", "astral-sh/", "gitleaks/", "softprops/", "orhun/"))
        ]
        assert action_refs, f"{path} must use GitHub actions"
        for ref in action_refs:
            assert ACTION_REF.match(ref), f"unpinned action reference: {ref}"
            assert "@main" not in ref and "@master" not in ref


def test_workflows_declare_permissions_and_concurrency() -> None:
    for path in (CI_PATH, RELEASE_PATH):
        workflow = _load(path)
        assert workflow.get("permissions") == {"contents": "read"}, path
        assert "concurrency" in workflow, path


def test_ci_matrix_covers_three_operating_systems() -> None:
    workflow = _load(CI_PATH)
    oses = _matrix_oses(workflow)

    assert {"ubuntu-latest", "windows-latest", "macos-latest"} <= oses
    smoke = workflow["jobs"]["installer-smoke"]
    assert smoke["strategy"]["matrix"]["os"] == [
        "ubuntu-latest",
        "windows-latest",
        "macos-latest",
    ]
    assert any("scripts/smoke_install.py" in step.get("run", "") for step in smoke["steps"])


def test_ci_e2e_and_eval_gate_steps() -> None:
    workflow = _load(CI_PATH)

    e2e_runs = " ".join(step.get("run", "") for step in workflow["jobs"]["e2e"]["steps"])
    assert "playwright install" in e2e_runs
    assert "pytest -m e2e" in e2e_runs

    gate = workflow["jobs"]["eval-gate"]
    gate_runs = " ".join(step.get("run", "") for step in gate["steps"])
    assert "sqlagent eval --llm replay --compare eval/baseline.json" in gate_runs
    assert any(
        step.get("uses", "").startswith("actions/upload-artifact@")
        and step.get("with", {}).get("path") == "eval/ci-report"
        for step in gate["steps"]
    )


def test_release_is_triggered_by_version_tags_and_attaches_artifacts() -> None:
    workflow = _load(RELEASE_PATH)
    triggers = _triggers(workflow)

    assert triggers["push"]["tags"] == ["v*"]
    all_steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    assert any(step.get("uses", "").startswith("orhun/git-cliff-action@") for step in all_steps)
    gh_release = next(
        step
        for step in all_steps
        if step.get("uses", "").startswith("softprops/action-gh-release@")
    )
    files = gh_release["with"]["files"]
    for expected in ("dist/*", "eval/reports/latest/report.md", "eval/reports/latest/summary.json"):
        assert expected in files
    assert gh_release["with"]["body_path"] == "RELEASE_NOTES.md"
