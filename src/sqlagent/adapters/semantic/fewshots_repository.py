"""YAML few-shot repository for GENERATE prompts (T7/D13).

Few-shots are trusted, hand-written resources; every entry is validated eagerly
so a broken file fails with ``ConfigError`` rather than a malformed prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sqlagent.domain.errors import ConfigError
from sqlagent.domain.models import Language
from sqlagent.domain.retrieval import FewShot

FEWSHOTS_SCHEMA = "sqlagent.fewshots/v1"
DEFAULT_FEWSHOTS_PATH = Path(__file__).resolve().parents[2] / "resources" / "fewshots.yaml"


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"few-shots: {where} must be a non-empty string")
    return value.strip()


def _tables(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"few-shots: {where} must be a list")
    return tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))


def _parse_entry(raw: Any, index: int) -> FewShot:
    if not isinstance(raw, dict):
        raise ConfigError(f"few-shots: entries[{index}] must be a mapping")
    where = f"entries[{index}]"
    language = _text(raw.get("language"), f"{where}.language")
    try:
        parsed_language = Language(language)
    except ValueError as exc:
        raise ConfigError(f"few-shots: {where}.language must be es or en") from exc
    return FewShot(
        question=_text(raw.get("question"), f"{where}.question"),
        sql=_text(raw.get("sql"), f"{where}.sql"),
        language=parsed_language,
        tables=_tables(raw.get("tables"), f"{where}.tables"),
    )


def load_fewshots(path: Path | None = None) -> tuple[FewShot, ...]:
    """Load and validate the bundled few-shot examples (deterministic order)."""

    source = Path(path) if path is not None else DEFAULT_FEWSHOTS_PATH
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read few-shots {source.name}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"cannot parse few-shots {source.name}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError("few-shots: document must be a mapping")
    if document.get("schema") != FEWSHOTS_SCHEMA:
        raise ConfigError(
            f"few-shots: unsupported schema {document.get('schema')!r} "
            f"(expected {FEWSHOTS_SCHEMA!r})"
        )
    entries = document.get("fewshots")
    if not isinstance(entries, list) or not entries:
        raise ConfigError("few-shots: fewshots must be a non-empty list")
    parsed = tuple(_parse_entry(entry, index) for index, entry in enumerate(entries))
    questions = [entry.question.casefold() for entry in parsed]
    if len(set(questions)) != len(questions):
        raise ConfigError("few-shots: duplicate question")
    return parsed


__all__ = ["DEFAULT_FEWSHOTS_PATH", "FEWSHOTS_SCHEMA", "load_fewshots"]
