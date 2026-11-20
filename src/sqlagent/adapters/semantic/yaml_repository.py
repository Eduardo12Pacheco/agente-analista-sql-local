"""YAML semantic-layer repository adapter (S6/D13).

The YAML file is data, not code: it is validated eagerly so a typo fails with a
clear ``ConfigError`` instead of surfacing later as a confusing SQL error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from sqlagent.domain.errors import ConfigError
from sqlagent.domain.semantic import (
    GlossaryEntry,
    Metric,
    Relationship,
    SemanticColumn,
    SemanticLayer,
    SemanticTable,
)

SEMANTIC_SCHEMA = "sqlagent.semantic-layer/v1"
DEFAULT_SEMANTIC_PATH = Path(__file__).resolve().parents[2] / "resources" / "semantic_layer.yaml"


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"semantic layer: {where} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _sequence(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"semantic layer: {where} must be a list")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"semantic layer: {where} must be a non-empty string")
    return value.strip()


def _text_tuple(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    items = _sequence(value, where)
    return tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(items))


def _boolean(value: Any, where: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ConfigError(f"semantic layer: {where} must be a boolean")
    return value


def _parse_column(raw: Any, table_name: str) -> SemanticColumn:
    item = _mapping(raw, f"tables[{table_name}].columns entry")
    name = _text(item.get("name"), f"tables[{table_name}].column.name")
    where = f"tables[{table_name}].{name}"
    return SemanticColumn(
        name=name,
        type=_text(item.get("type"), f"{where}.type"),
        description_en=_text(item.get("description_en"), f"{where}.description_en"),
        description_es=_text(item.get("description_es"), f"{where}.description_es"),
        synonyms=_text_tuple(item.get("synonyms"), f"{where}.synonyms"),
        lookupable=_boolean(item.get("lookupable"), f"{where}.lookupable"),
        samples=_text_tuple(item.get("samples"), f"{where}.samples"),
    )


def _parse_table(raw: Any) -> SemanticTable:
    item = _mapping(raw, "tables entry")
    name = _text(item.get("name"), "table.name")
    where = f"tables[{name}]"
    columns = _sequence(item.get("columns"), f"{where}.columns")
    if not columns:
        raise ConfigError(f"semantic layer: {where}.columns must not be empty")
    return SemanticTable(
        name=name,
        description_en=_text(item.get("description_en"), f"{where}.description_en"),
        description_es=_text(item.get("description_es"), f"{where}.description_es"),
        synonyms=_text_tuple(item.get("synonyms"), f"{where}.synonyms"),
        columns=tuple(_parse_column(column, name) for column in columns),
    )


def _parse_metric(raw: Any) -> Metric:
    item = _mapping(raw, "metrics entry")
    name = _text(item.get("name"), "metric.name")
    where = f"metrics[{name}]"
    tables = _text_tuple(item.get("tables"), f"{where}.tables")
    if not tables:
        raise ConfigError(f"semantic layer: {where}.tables must not be empty")
    return Metric(
        name=name,
        expression_sql=_text(item.get("expression_sql"), f"{where}.expression_sql"),
        description_en=_text(item.get("description_en"), f"{where}.description_en"),
        description_es=_text(item.get("description_es"), f"{where}.description_es"),
        synonyms=_text_tuple(item.get("synonyms"), f"{where}.synonyms"),
        tables=tables,
    )


def _parse_relationship(raw: Any) -> Relationship:
    item = _mapping(raw, "relationships entry")
    return Relationship(
        from_=_text(item.get("from"), "relationship.from"),
        to=_text(item.get("to"), "relationship.to"),
        on=_text(item.get("on"), "relationship.on"),
    )


def _parse_glossary(raw: Any) -> GlossaryEntry:
    item = _mapping(raw, "glossary entry")
    terms = _text_tuple(item.get("terms"), "glossary.terms")
    if not terms:
        raise ConfigError("semantic layer: glossary.terms must not be empty")
    return GlossaryEntry(terms=terms, meaning=_text(item.get("meaning"), "glossary.meaning"))


def _parse_document(document: Any) -> SemanticLayer:
    root = _mapping(document, "document")
    schema = root.get("schema")
    if schema != SEMANTIC_SCHEMA:
        raise ConfigError(
            f"semantic layer: unsupported schema {schema!r} (expected {SEMANTIC_SCHEMA!r})"
        )
    tables = _sequence(root.get("tables"), "tables")
    if not tables:
        raise ConfigError("semantic layer: tables must not be empty")
    return SemanticLayer(
        tables=tuple(_parse_table(table) for table in tables),
        metrics=tuple(_parse_metric(metric) for metric in root.get("metrics") or []),
        relationships=tuple(
            _parse_relationship(relationship) for relationship in root.get("relationships") or []
        ),
        glossary=tuple(entry for entry in map(_parse_glossary, root.get("glossary") or [])),
        data_quirks=_text_tuple(root.get("data_quirks"), "data_quirks"),
    )


class YamlSemanticLayerRepository:
    """Load and validate the bundled (or an alternative) semantic-layer YAML."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_SEMANTIC_PATH

    def load(self) -> SemanticLayer:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"cannot read semantic layer {self.path.name}: {exc}") from exc
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"cannot parse semantic layer {self.path.name}: {exc}") from exc
        return _parse_document(document)


__all__ = ["DEFAULT_SEMANTIC_PATH", "SEMANTIC_SCHEMA", "YamlSemanticLayerRepository"]
