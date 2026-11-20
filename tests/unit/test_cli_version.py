"""The CLI exposes the version and stays importable as a console script."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import sqlagent.__main__ as entrypoint
from sqlagent import __version__
from sqlagent.adapters.cli.main import app


@pytest.mark.unit
def test_cli_version_flag_prints_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"sqlagent {__version__}"


@pytest.mark.unit
def test_cli_without_arguments_shows_help() -> None:
    result = CliRunner().invoke(app, [])

    assert result.exit_code in (0, 2)
    assert "sqlagent" in result.output.lower()


@pytest.mark.unit
def test_module_entrypoint_runs_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    def fake_app() -> None:
        calls.append(True)

    monkeypatch.setattr(entrypoint, "app", fake_app)
    entrypoint.run()

    assert calls == [True]
