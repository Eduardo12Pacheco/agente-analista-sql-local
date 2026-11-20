"""Loading and validation of the bundled semantic layer YAML (S6/D13)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sqlagent.adapters.semantic.yaml_repository import (
    DEFAULT_SEMANTIC_PATH,
    YamlSemanticLayerRepository,
)
from sqlagent.domain.errors import ConfigError

pytestmark = pytest.mark.unit


def test_default_resource_exists_and_loads() -> None:
    assert DEFAULT_SEMANTIC_PATH.is_file()

    layer = YamlSemanticLayerRepository().load()

    assert len(layer.tables) == 6
    assert len(layer.metrics) >= 8
    assert len(layer.relationships) >= 5
    assert len(layer.glossary) >= 20
    assert layer.data_quirks
    assert layer.table("tenders") is not None
    assert layer.column("tenders.procurement_type") is not None


def test_relationship_from_key_is_mapped_to_from_underscore() -> None:
    layer = YamlSemanticLayerRepository().load()

    relationships = {(item.from_, item.to) for item in layer.relationships}
    assert ("tenders.buyer_id", "buyers.buyer_id") in relationships


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    repo = YamlSemanticLayerRepository(tmp_path / "missing.yaml")

    with pytest.raises(ConfigError, match="semantic layer"):
        repo.load()


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("tables: [unclosed", encoding="utf-8")

    with pytest.raises(ConfigError, match="semantic layer"):
        YamlSemanticLayerRepository(path).load()


def test_wrong_schema_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad-schema.yaml"
    path.write_text(
        yaml.safe_dump({"schema": "sqlagent.semantic-layer/v2", "tables": []}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="schema"):
        YamlSemanticLayerRepository(path).load()


def test_missing_bilingual_description_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "missing-description.yaml"
    document = {
        "schema": "sqlagent.semantic-layer/v1",
        "tables": [
            {
                "name": "tenders",
                "description_en": "Tenders",
                "description_es": "",
                "columns": [
                    {
                        "name": "tender_id",
                        "type": "VARCHAR",
                        "description_en": "Identifier",
                        "description_es": "Identificador",
                    }
                ],
            }
        ],
    }
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    with pytest.raises(ConfigError, match="description_es"):
        YamlSemanticLayerRepository(path).load()


def test_minimal_document_loads_with_empty_optional_sections(tmp_path: Path) -> None:
    path = tmp_path / "minimal.yaml"
    document = {
        "schema": "sqlagent.semantic-layer/v1",
        "tables": [
            {
                "name": "tenders",
                "description_en": "Tenders",
                "description_es": "Procesos",
                "columns": [
                    {
                        "name": "tender_id",
                        "type": "VARCHAR",
                        "description_en": "Identifier",
                        "description_es": "Identificador",
                    }
                ],
            }
        ],
    }
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    layer = YamlSemanticLayerRepository(path).load()

    assert layer.metrics == ()
    assert layer.relationships == ()
    assert layer.glossary == ()
    assert layer.data_quirks == ()
    assert layer.tables[0].columns[0].lookupable is False
