#!/usr/bin/env python3
"""Installer smoke test for a built wheel (T13 / S36).

The script is intentionally standard-library only and cross-platform: it finds
the wheel in ``dist/``, installs it as an isolated ``uv tool``, exercises the
real console script offline (version, data verify, doctor, replay ask) and
always uninstalls it afterwards.  It needs neither Ollama nor a network
connection at run time.

Usage::

    uv build
    uv run python scripts/smoke_install.py [--wheel PATH] [--dist DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PACKAGE = "local-sql-analyst-agent"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "dist"


def fail(message: str) -> None:
    """Abort the smoke test with a visible error and a non-zero status."""

    print(f"FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_wheel(dist_dir: Path) -> Path:
    """Return the single wheel in ``dist_dir`` (fail loudly otherwise)."""

    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        fail(f"no wheel found in {dist_dir}; run `uv build` first")
    if len(wheels) > 1:
        fail(f"expected one wheel in {dist_dir}, found {len(wheels)}")
    return wheels[0]


def parse_question(text: str, question_id: str = "q001") -> str:
    """Extract a question string from the flat benchmark YAML without PyYAML."""

    header = re.compile(rf"^- id: {re.escape(question_id)}\s*$", re.MULTILINE)
    match = header.search(text)
    if match is None:
        fail(f"benchmark item {question_id} not found")
    block = text[match.end() :]
    next_item = re.search(r"^- id: ", block, re.MULTILINE)
    if next_item is not None:
        block = block[: next_item.start()]
    question = re.search(r"^  question:\s*(.+?)\s*$", block, re.MULTILINE)
    if question is None:
        fail(f"benchmark item {question_id} has no question text")
    value = question.group(1)
    if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
        value = value[1:-1]
    if not value:
        fail(f"benchmark item {question_id} has an empty question")
    return value


def find_cassettes(resources_dir: Path) -> list[Path]:
    """Return every recorded cassette below ``resources_dir`` (empty is allowed)."""

    return sorted(resources_dir.rglob("*.jsonl"))


def validate_answer_payload(payload: Any) -> None:
    """Assert the replay answer has the fields the installer promises."""

    if not isinstance(payload, dict):
        fail("answer JSON is not an object")
    if payload.get("status") != "ok":
        fail(f"replay answer status is {payload.get('status')!r}, expected 'ok'")
    sql = payload.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        fail("replay answer has no SQL")
    result = payload.get("result")
    if not isinstance(result, dict):
        fail("replay answer has no result object")
    rows = result.get("rows")
    if not isinstance(rows, list) or not rows:
        fail("replay answer result has no rows")


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    capture: bool = True,
    timeout: float = 600,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed command list, no shell
            command,
            check=False,
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            cwd=ROOT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(f"could not run {command[0]}: {exc}")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        fail(f"{' '.join(command)} exited {completed.returncode}: {detail[-800:]}")
    return completed


def _uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        fail("uv is not installed or not on PATH")
    return uv


def _tool_bin_dir(uv: str, env: dict[str, str]) -> Path:
    completed = _run([uv, "tool", "dir", "--bin"], env=env)
    return Path(completed.stdout.strip())


def _tool_root(uv: str, env: dict[str, str]) -> Path:
    completed = _run([uv, "tool", "dir"], env=env)
    return Path(completed.stdout.strip())


def _tool_python(tool_root: Path, env: dict[str, str]) -> Path:
    candidates = sorted(tool_root.glob("local*sql*analyst*agent"))
    if not candidates:
        fail(f"installed tool environment not found under {tool_root}")
    package_dir = candidates[0]
    for relative in ("bin/python", "Scripts/python.exe", "bin/python3"):
        candidate = package_dir / relative
        if candidate.is_file():
            return candidate
    fail(f"python interpreter not found in {package_dir}")


def _console_script(bin_dir: Path) -> Path:
    for name in ("sqlagent", "sqlagent.exe"):
        candidate = bin_dir / name
        if candidate.is_file():
            return candidate
    fail(f"sqlagent console script not found in {bin_dir}")


def _read_installed_resource(python: Path, relative: str, env: dict[str, str]) -> str:
    code = (
        "from importlib.resources import files\n"
        f"print(files('sqlagent').joinpath({relative!r}).read_text(encoding='utf-8'))\n"
    )
    return _run([str(python), "-c", code], env=env).stdout


def _installed_cassettes(python: Path, env: dict[str, str]) -> list[str]:
    code = (
        "from importlib.resources import files\n"
        "root = files('sqlagent').joinpath('resources/recordings')\n"
        "names = sorted(str(p) for p in root.rglob('*.jsonl'))\n"
        "print('\\n'.join(names))\n"
    )
    output = _run([str(python), "-c", code], env=env).stdout
    return [line for line in output.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST, help="Directory with the wheel.")
    parser.add_argument("--wheel", type=Path, help="Explicit wheel path (overrides --dist).")
    args = parser.parse_args(argv)

    uv = _uv()
    wheel = args.wheel or find_wheel(args.dist)
    if not wheel.is_file():
        fail(f"wheel does not exist: {wheel}")

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("SQLAGENT_LAKEHOUSE_MANIFEST", None)

    with tempfile.TemporaryDirectory(prefix="sqlagent-smoke-data-") as data_dir:
        env["SQLAGENT_DATA_DIR"] = data_dir
        installed = False
        try:
            _run([uv, "tool", "install", "--force", str(wheel)], env=env)
            installed = True
            print(f"OK install wheel: {wheel.name}")

            bin_dir = _tool_bin_dir(uv, env)
            tool_root = _tool_root(uv, env)
            cli = _console_script(bin_dir)
            python = _tool_python(tool_root, env)

            version = _run([str(cli), "--version"], env=env).stdout.strip()
            if not version.startswith("sqlagent "):
                fail(f"unexpected --version output: {version!r}")
            print(f"OK version: {version}")

            _run([str(cli), "data", "verify"], env=env)
            print("OK data verify")

            _run([str(cli), "doctor", "--offline"], env=env)
            print("OK doctor --offline")

            cassettes = _installed_cassettes(python, env)
            if not cassettes:
                print("SKIPPED (no recordings): replay ask has no committed cassette")
            else:
                benchmark = _read_installed_resource(
                    python, "resources/benchmark/v1/questions.yaml", env
                )
                question = parse_question(benchmark, "q001")
                completed = _run(
                    [str(cli), "ask", "--llm", "replay", "--json", question],
                    env=env,
                )
                try:
                    payload = json.loads(completed.stdout)
                except json.JSONDecodeError as exc:
                    fail(f"replay ask did not print one JSON document: {exc}")
                validate_answer_payload(payload)
                print("OK replay ask (status=ok, SQL and rows present)")

            return 0
        finally:
            if installed:
                _run([uv, "tool", "uninstall", PACKAGE], env=env)
                print("OK uninstall")


if __name__ == "__main__":
    raise SystemExit(main())
