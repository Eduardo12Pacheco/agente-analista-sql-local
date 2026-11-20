"""Tests for typed settings and the CONFIGURATION.md doc-sync rule (S35/D26)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from sqlagent.config import DEFAULT_MODEL, Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DOC = REPO_ROOT / "docs" / "CONFIGURATION.md"

_ENV_NAMES = {f"SQLAGENT_{name.upper()}" for name in Settings.model_fields}


@pytest.fixture(autouse=True)
def clear_sqlagent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_d26() -> None:
    settings = Settings()

    assert settings.llm_backend == "ollama"
    assert settings.ollama_url == "http://127.0.0.1:11434"
    assert settings.model == DEFAULT_MODEL == "qwen3:8b"
    assert settings.num_ctx == 8192
    assert settings.temperature == 0.0
    assert settings.seed == 42
    assert settings.request_timeout_s == 120.0
    assert settings.num_predict == 768
    assert settings.allow_remote_llm is False
    assert settings.max_rows == 1000
    assert settings.ui_rows == 200
    assert settings.query_timeout_s == 20.0
    assert settings.memory_limit == "2GB"
    assert settings.threads == 4
    assert settings.max_repairs == 2
    assert settings.max_tool_calls == 3
    assert settings.lakehouse_manifest is None
    assert settings.log_level == "INFO"
    assert settings.log_format == "console"
    assert settings.ui_lang == "auto"


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLAGENT_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setenv("SQLAGENT_OLLAMA_URL", "http://127.0.0.1:11435")
    monkeypatch.setenv("SQLAGENT_ALLOW_REMOTE_LLM", "1")
    monkeypatch.setenv("SQLAGENT_MAX_REPAIRS", "0")
    monkeypatch.setenv("SQLAGENT_LOG_FORMAT", "json")

    settings = Settings()

    assert settings.model == "qwen2.5-coder:7b"
    assert settings.ollama_url == "http://127.0.0.1:11435"
    assert settings.allow_remote_llm is True
    assert settings.max_repairs == 0
    assert settings.log_format == "json"


def test_dotenv_is_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("SQLAGENT_MODEL=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert Settings().model == DEFAULT_MODEL


def test_invalid_values_raise_validation_error() -> None:
    with pytest.raises(ValidationError):
        Settings(temperature=9.0)
    with pytest.raises(ValidationError):
        Settings(num_ctx=-1)
    with pytest.raises(ValidationError):
        Settings(log_format="xml")


def test_unknown_environment_variable_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQLAGENT_NOT_A_SETTING", "whatever")

    assert Settings().model == DEFAULT_MODEL


def test_configuration_doc_documents_every_setting() -> None:
    text = CONFIG_DOC.read_text(encoding="utf-8")

    documented = set(re.findall(r"SQLAGENT_[A-Z0-9_]+", text))

    assert documented == _ENV_NAMES


def test_configuration_doc_is_linked_from_settings_module() -> None:
    source = (REPO_ROOT / "src" / "sqlagent" / "config.py").read_text(encoding="utf-8")

    assert "docs/CONFIGURATION.md" in source
