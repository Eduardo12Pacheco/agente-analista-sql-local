"""Tests for the ``sqlagent doctor`` command and its offline/online behaviour (S39)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from sqlagent.adapters.cli import doctor as doctor_module
from sqlagent.adapters.cli.main import app
from sqlagent.adapters.llm.ollama import OllamaProbe


def combined_output(result: Any) -> str:
    return f"{result.stdout}{getattr(result, 'stderr', '')}"


def test_doctor_offline_exits_zero_and_reports_warehouse(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("SQLAGENT_DATA_DIR", str(tmp_path / "data"))

    result = CliRunner().invoke(app, ["doctor", "--offline"])

    output = combined_output(result)
    assert result.exit_code == 0
    assert "warehouse OK" in output
    assert "[OK] warehouse" in output
    assert "skipped (--offline)" in output
    assert "demo:" in output


def test_doctor_exits_three_when_warehouse_is_broken(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("SQLAGENT_WAREHOUSE_PATH", str(tmp_path / "missing.duckdb"))

    result = CliRunner().invoke(app, ["doctor", "--offline"])

    output = combined_output(result)
    assert result.exit_code == 3
    assert "warehouse broken" in output
    assert "warehouse: broken" in output


def test_doctor_without_ollama_reports_commands_and_exits_zero(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("SQLAGENT_DATA_DIR", str(tmp_path / "data"))

    class UnreachableOllama:
        def __init__(self, settings: object) -> None:
            self.settings = settings

        def probe(self) -> OllamaProbe:
            return OllamaProbe(reachable=False, detail="ConnectError: refused")

        def close(self) -> None:
            return None

    monkeypatch.setattr(doctor_module, "OllamaLLM", UnreachableOllama)

    result = CliRunner().invoke(app, ["doctor"])

    output = combined_output(result)
    assert result.exit_code == 0
    assert "Ollama: not reachable" in output
    assert "scripts/ollama-docker.sh up" in output
    assert "scripts/ollama-docker.sh pull qwen2.5-coder:7b" in output
    assert "warehouse OK" in output


def test_doctor_reports_model_presence(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("SQLAGENT_DATA_DIR", str(tmp_path / "data"))

    class PresentOllama:
        def __init__(self, settings: object) -> None:
            self.settings = settings

        def probe(self) -> OllamaProbe:
            return OllamaProbe(
                reachable=True,
                version="0.40.16",
                models=("qwen2.5-coder:7b",),
                model_present=True,
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(doctor_module, "OllamaLLM", PresentOllama)

    result = CliRunner().invoke(app, ["doctor"])

    output = combined_output(result)
    assert result.exit_code == 0
    assert "reachable (version 0.40.16)" in output
    assert "qwen2.5-coder:7b is installed" in output


def test_doctor_reports_missing_model_with_pull_command(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("SQLAGENT_DATA_DIR", str(tmp_path / "data"))

    class EmptyOllama:
        def __init__(self, settings: object) -> None:
            self.settings = settings

        def probe(self) -> OllamaProbe:
            return OllamaProbe(reachable=True, version="0.40.16", models=(), model_present=False)

        def close(self) -> None:
            return None

    monkeypatch.setattr(doctor_module, "OllamaLLM", EmptyOllama)

    result = CliRunner().invoke(app, ["doctor"])

    output = combined_output(result)
    assert result.exit_code == 0
    assert "qwen2.5-coder:7b is not installed" in output
    assert "ollama pull qwen2.5-coder:7b" in output
