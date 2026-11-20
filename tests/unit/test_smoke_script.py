"""The installer smoke helper is testable without installing anything (T13)."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "smoke_install.py"

pytestmark = pytest.mark.unit


def _load_script() -> ModuleType:
    assert SCRIPT.is_file(), f"missing smoke script: {SCRIPT}"
    spec = importlib.util.spec_from_file_location("smoke_install", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_wheel_selects_the_single_build(tmp_path: Path) -> None:
    module = _load_script()
    wheel = tmp_path / "local_sql_analyst_agent-0.1.0.dev0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    assert module.find_wheel(tmp_path) == wheel


def test_find_wheel_fails_without_build(tmp_path: Path) -> None:
    module = _load_script()

    with pytest.raises(SystemExit) as excinfo:
        module.find_wheel(tmp_path)
    assert excinfo.value.code != 0


def test_parse_question_reads_q001_from_benchmark_yaml() -> None:
    module = _load_script()
    text = (ROOT / "src/sqlagent/resources/benchmark/v1/questions.yaml").read_text(encoding="utf-8")

    assert module.parse_question(text, "q001") == "How many tenders are in the database?"
    assert module.parse_question(text, "q002") == "¿Cuál es el monto total adjudicado en dólares?"


def test_parse_question_rejects_a_missing_item() -> None:
    module = _load_script()

    with pytest.raises(SystemExit):
        module.parse_question("- id: q999\n  question: nope\n", "q001")


def test_find_cassettes_walks_the_recording_resource(tmp_path: Path) -> None:
    module = _load_script()
    empty = tmp_path / "empty"
    empty.mkdir()

    assert module.find_cassettes(empty) == []

    recording = tmp_path / "qwen2.5-coder-7b" / "p1.jsonl"
    recording.parent.mkdir()
    recording.write_text("{}\n", encoding="utf-8")

    assert module.find_cassettes(tmp_path) == [recording]


def test_validate_answer_payload_accepts_a_real_answer_shape() -> None:
    module = _load_script()
    payload = {
        "status": "ok",
        "sql": "SELECT COUNT(*) AS n FROM tenders",
        "result": {"columns": [{"name": "n", "type": "BIGINT"}], "rows": [[121072]]},
    }

    module.validate_answer_payload(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "failed", "sql": "", "result": None},
        {"status": "ok", "sql": "", "result": {"rows": [[1]]}},
        {"status": "ok", "sql": "SELECT 1", "result": {"rows": []}},
        {"status": "ok", "sql": "SELECT 1", "result": "not-a-dict"},
    ],
)
def test_validate_answer_payload_rejects_invalid_results(payload: object) -> None:
    module = _load_script()

    with pytest.raises(SystemExit):
        module.validate_answer_payload(payload)


def test_script_imports_only_the_standard_library() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    assert imported
    assert imported <= sys.stdlib_module_names
