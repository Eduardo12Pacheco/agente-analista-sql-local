"""``sqlagent serve`` CLI contract (D25/S28): options, demo mode and exit codes."""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from sqlagent.adapters.cli import main as main_module
from sqlagent.adapters.cli.main import app
from sqlagent.domain.errors import ConfigError, WarehouseUnavailable

pytestmark = pytest.mark.unit

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_serve_help_lists_every_option() -> None:
    result = CliRunner().invoke(app, ["serve", "--help"])

    assert result.exit_code == 0
    plain = _ANSI.sub("", result.stdout)
    for option in ("--host", "--port", "--llm", "--model", "--demo", "--open", "--manifest"):
        assert option in plain


@pytest.fixture
def fake_uvicorn(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}

    def fake_run(application, *, host: str, port: int, log_level: str) -> None:
        captured["application"] = application
        captured["host"] = host
        captured["port"] = port
        captured["log_level"] = log_level

    monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
    return captured


def test_demo_serves_replay_backend_on_the_expected_port(
    monkeypatch: pytest.MonkeyPatch, fake_uvicorn: dict[str, object]
) -> None:
    seen: dict[str, object] = {}

    def fake_create_app(settings):
        seen["settings"] = settings
        return object()

    monkeypatch.setattr(main_module, "create_app", fake_create_app)
    result = CliRunner().invoke(app, ["serve", "--demo", "--port", "8765"])

    assert result.exit_code == 0
    settings = seen["settings"]
    assert settings.llm_backend == "replay"
    assert fake_uvicorn["port"] == 8765
    assert fake_uvicorn["host"] == "127.0.0.1"


def test_default_port_is_in_the_portfolio_range(
    monkeypatch: pytest.MonkeyPatch, fake_uvicorn: dict[str, object]
) -> None:
    monkeypatch.setattr(main_module, "create_app", lambda settings: object())
    result = CliRunner().invoke(app, ["serve", "--demo"])

    assert result.exit_code == 0
    assert 17000 <= int(fake_uvicorn["port"]) <= 17999


def test_serve_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fail(settings):
        nonlocal called
        called = True
        raise AssertionError("create_app must not run")

    monkeypatch.setattr(main_module, "create_app", fail)
    result = CliRunner().invoke(app, ["serve", "--llm", "cloud"])

    assert result.exit_code == 2
    assert not called


def test_serve_maps_missing_warehouse_to_exit_three(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(settings):
        raise WarehouseUnavailable("bundle missing")

    monkeypatch.setattr(main_module, "create_app", broken)
    result = CliRunner().invoke(app, ["serve", "--demo"])

    assert result.exit_code == 3
    assert "warehouse unavailable" in result.stdout + result.stderr


def test_serve_maps_config_error_to_exit_two(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(settings):
        raise ConfigError("bad settings")

    monkeypatch.setattr(main_module, "create_app", broken)
    result = CliRunner().invoke(app, ["serve"])

    assert result.exit_code == 2
    assert "bad settings" in result.stdout + result.stderr


def test_open_browser_schedules_launch(
    monkeypatch: pytest.MonkeyPatch, fake_uvicorn: dict[str, object]
) -> None:
    opened: list[str] = []

    class FakeTimer:
        def __init__(self, interval, function, args=()):
            self.interval = interval
            self.function = function
            self.args = args

        def start(self) -> None:
            self.function(*self.args)

    monkeypatch.setattr(main_module, "create_app", lambda settings: object())
    monkeypatch.setattr(main_module.threading, "Timer", FakeTimer)
    monkeypatch.setattr(main_module.webbrowser, "open", opened.append)

    result = CliRunner().invoke(app, ["serve", "--demo", "--port", "17081", "--open"])

    assert result.exit_code == 0
    assert opened == ["http://127.0.0.1:17081/"]
