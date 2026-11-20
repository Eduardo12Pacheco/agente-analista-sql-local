"""Typed application settings (D26), loaded from ``SQLAGENT_*`` environment variables.

``.env`` files are intentionally never read so a stray file cannot change a
deterministic run.  Every field is documented in ``docs/CONFIGURATION.md`` and a
test fails when the table and ``Settings.model_fields`` drift apart (S35).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Chosen in T12 from benchmark v1: qwen2.5-coder:7b scored higher EX than qwen3:8b (D10).
DEFAULT_MODEL = "qwen2.5-coder:7b"


def _default_data_dir() -> Path:
    return Path(user_data_dir("sqlagent"))


class Settings(BaseSettings):
    """Runtime configuration with environment overrides."""

    model_config = SettingsConfigDict(
        env_prefix="SQLAGENT_",
        env_file=None,
        extra="ignore",
        frozen=True,
    )

    # -- LLM backend (D26) --------------------------------------------
    llm_backend: Literal["ollama", "replay"] = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = DEFAULT_MODEL
    num_ctx: int = Field(default=8192, ge=512)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int = 42
    request_timeout_s: float = Field(default=120.0, gt=0)
    num_predict: int = Field(default=768, ge=1)
    allow_remote_llm: bool = False

    # -- Warehouse limits (D15) ---------------------------------------
    max_rows: int = Field(default=1_000, ge=1)
    ui_rows: int = Field(default=200, ge=1)
    query_timeout_s: float = Field(default=20.0, gt=0)
    memory_limit: str = "2GB"
    threads: int = Field(default=4, ge=1)

    # -- Agent bounds (D5) --------------------------------------------
    max_repairs: int = Field(default=2, ge=0)
    max_tool_calls: int = Field(default=3, ge=0)

    # -- Paths --------------------------------------------------------
    data_dir: Path = Field(default_factory=_default_data_dir)
    warehouse_path: Path | None = None
    lakehouse_manifest: Path | None = None

    # -- Logging and UI -----------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["console", "json"] = "console"
    ui_lang: Literal["auto", "es", "en"] = "auto"
