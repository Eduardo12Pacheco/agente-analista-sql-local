"""Typed application settings (D26), loaded from ``SQLAGENT_*`` environment variables.

T4 only needs the warehouse-related fields; T6 extends this module with the
LLM, logging and UI settings.  ``.env`` files are intentionally never read so a
stray file cannot change a deterministic run.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    data_dir: Path = Field(default_factory=_default_data_dir)
    warehouse_path: Path | None = None
    max_rows: int = Field(default=1_000, ge=1)
    ui_rows: int = Field(default=200, ge=1)
    query_timeout_s: float = Field(default=20.0, gt=0)
    memory_limit: str = "2GB"
    threads: int = Field(default=4, ge=1)
