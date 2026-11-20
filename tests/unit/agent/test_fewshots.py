"""Bundled few-shot examples: size, languages, SQL policy and validation (T7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sqlagent.adapters.semantic.fewshots_repository import (
    DEFAULT_FEWSHOTS_PATH,
    load_fewshots,
)
from sqlagent.domain.errors import ConfigError
from sqlagent.domain.models import Language
from sqlagent.domain.sql_policy import SqlPolicy


def test_bundled_fewshots_are_bilingual_and_plentiful() -> None:
    fewshots = load_fewshots()
    assert len(fewshots) >= 8
    assert {shot.language for shot in fewshots} == {Language.ES, Language.EN}
    assert len({shot.question.casefold() for shot in fewshots}) == len(fewshots)


def test_every_fewshot_sql_passes_the_guardrails() -> None:
    policy = SqlPolicy()
    for shot in load_fewshots():
        validated = policy.validate(shot.sql)
        assert validated.sql
        assert set(validated.tables).issubset(policy.catalog_tables)


def test_loader_raises_config_error_for_bad_files(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigError):
        load_fewshots(missing)

    broken = tmp_path / "broken.yaml"
    broken.write_text("schema: nope\nfewshots: []\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_fewshots(broken)

    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(
        "schema: sqlagent.fewshots/v1\n"
        "fewshots:\n"
        "  - {question: Same?, sql: SELECT 1, language: en}\n"
        "  - {question: same?, sql: SELECT 2, language: es}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_fewshots(duplicate)

    bad_language = tmp_path / "language.yaml"
    bad_language.write_text(
        "schema: sqlagent.fewshots/v1\n"
        "fewshots:\n"
        "  - {question: Hola?, sql: SELECT 1, language: fr}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_fewshots(bad_language)


def test_default_path_points_at_the_bundled_resource() -> None:
    assert DEFAULT_FEWSHOTS_PATH.is_file()
    assert DEFAULT_FEWSHOTS_PATH.name == "fewshots.yaml"
