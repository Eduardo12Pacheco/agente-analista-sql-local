"""``sqlagent ask`` CLI contract: options, rendering, JSON and exit codes (D25)."""

from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

from sqlagent.adapters.cli import main as main_module
from sqlagent.adapters.cli.main import app
from sqlagent.adapters.llm.scripted import ScriptedLLM
from sqlagent.domain.errors import WarehouseUnavailable


def final(sql: str = "SELECT COUNT(*) AS n FROM tenders") -> str:
    return json.dumps({"plan": ["count"], "action": "final_sql", "sql": sql})


def narrate() -> str:
    return json.dumps({"answer": "Hay 3 procesos."})


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_ask_help_lists_every_d25_option() -> None:
    result = CliRunner().invoke(app, ["ask", "--help"])
    assert result.exit_code == 0
    plain = _ANSI.sub("", result.stdout)
    for option in (
        "--lang",
        "--llm",
        "--model",
        "--no-narrate",
        "--json",
        "--trace",
        "--manifest",
    ):
        assert option in plain


def test_ask_prints_sql_table_and_exits_zero(make_agent, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent(ScriptedLLM([final(), narrate()]))
    monkeypatch.setattr(main_module, "build_agent", lambda settings, **kwargs: agent)

    result = CliRunner().invoke(app, ["ask", "¿Cuántos procesos hay?"])

    assert result.exit_code == 0
    assert "Hay 3 procesos." in result.stdout
    assert "SELECT COUNT(*)" in result.stdout
    assert "Result (1 rows)" in result.stdout
    assert "kpi" in result.stdout.lower()


def test_ask_json_prints_one_document(make_agent, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent(ScriptedLLM([final(), narrate()]))
    monkeypatch.setattr(main_module, "build_agent", lambda settings, **kwargs: agent)

    result = CliRunner().invoke(app, ["ask", "--json", "¿Cuántos procesos hay?"])

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["status"] == "ok"
    assert document["language"] == "es"
    assert document["sql"].startswith("SELECT COUNT(*)")
    assert document["result"]["rows"] == [[3]]
    assert document["chart"]["kind"] == "kpi"
    assert document["trace"]["llm_calls"] == 2


def test_ask_failed_answer_exits_one(make_agent, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent(ScriptedLLM(["nope", "still nope"]))
    monkeypatch.setattr(main_module, "build_agent", lambda settings, **kwargs: agent)

    result = CliRunner().invoke(app, ["ask", "--json", "How many tenders?"])

    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "failed"


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (["--lang", "fr", "question"], 2),
        (["--llm", "openai", "question"], 2),
    ],
)
def test_ask_rejects_invalid_options(
    arguments: list[str], code: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def fail_build(settings, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("build_agent must not run for invalid options")

    monkeypatch.setattr(main_module, "build_agent", fail_build)
    result = CliRunner().invoke(app, ["ask", *arguments])
    assert result.exit_code == code
    assert not called


def test_ask_warehouse_missing_exits_three(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(settings, **kwargs):
        raise WarehouseUnavailable("warehouse file is missing")

    monkeypatch.setattr(main_module, "build_agent", broken)
    result = CliRunner().invoke(app, ["ask", "question"])
    assert result.exit_code == 3
    assert "warehouse unavailable" in result.stdout + result.stderr


def test_ask_trace_flag_renders_attempts(make_agent, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent(ScriptedLLM([final(), narrate()]))
    monkeypatch.setattr(main_module, "build_agent", lambda settings, **kwargs: agent)
    result = CliRunner().invoke(app, ["ask", "--trace", "¿Cuántos procesos hay?"])
    assert result.exit_code == 0
    assert "Trace" in result.stdout
    assert "llm_calls" in result.stdout
    assert "retrieved_tables" in result.stdout


def test_ask_no_narrate_uses_template(make_agent, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = make_agent(ScriptedLLM([final()]), narrate=False)
    monkeypatch.setattr(main_module, "build_agent", lambda settings, **kwargs: agent)
    result = CliRunner().invoke(app, ["ask", "--no-narrate", "¿Cuántos procesos hay?"])
    assert result.exit_code == 0
    assert "Se encontró 1 fila" in result.stdout
