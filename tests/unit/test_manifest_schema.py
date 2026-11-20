"""Lakehouse manifest model, schema export and docs example (T11/S31/D28)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sqlagent.adapters.warehouse.lakehouse import (
    LAKEHOUSE_SCHEMA,
    LakehouseManifest,
    load_manifest,
)
from sqlagent.domain.errors import ConfigError

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = REPO_ROOT / "docs" / "lakehouse-manifest.schema.json"
EXAMPLE_FILE = REPO_ROOT / "docs" / "examples" / "lakehouse-manifest.example.json"
SHA = "a" * 64


def manifest_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": LAKEHOUSE_SCHEMA,
        "name": "sibling-lakehouse",
        "generated_at": "2026-11-20T10:00:00Z",
        "duckdb_file": "warehouse/sibling.duckdb",
        "sha256": SHA,
        "tables": [
            {
                "name": "sales",
                "description": "One row per sale.",
                "columns": [
                    {
                        "name": "sale_id",
                        "type": "VARCHAR",
                        "description": "Stable sale identifier.",
                        "synonyms": ["venta", "id"],
                        "lookupable": False,
                        "samples": [],
                    },
                    {
                        "name": "amount_usd",
                        "type": "DOUBLE",
                        "description": "Sale amount in US dollars.",
                    },
                    {
                        "name": "region",
                        "type": "VARCHAR",
                        "description": "Region the sale belongs to.",
                    },
                ],
            },
            {
                "name": "regions",
                "description": "Regions with their sales manager.",
                "columns": [
                    {"name": "region", "type": "VARCHAR", "description": "Region name."},
                    {"name": "manager", "type": "VARCHAR", "description": "Manager name."},
                ],
            },
        ],
        "relationships": [{"from": "sales.region", "to": "regions.region"}],
        "language": "en",
    }
    document.update(overrides)
    return document


def test_schema_file_matches_the_model() -> None:
    committed = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))

    assert committed == LakehouseManifest.model_json_schema()


def test_documented_example_validates_against_the_contract() -> None:
    document = json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))

    manifest = LakehouseManifest.model_validate(document)

    assert manifest.name == "example-lakehouse"
    assert manifest.schema_ == LAKEHOUSE_SCHEMA
    assert {table.name for table in manifest.tables} == {"countries", "gdp"}


def test_valid_document_parses_into_frozen_dataclasses() -> None:
    manifest = LakehouseManifest.model_validate(manifest_document())

    assert manifest.schema_ == LAKEHOUSE_SCHEMA
    assert manifest.duckdb_file == Path("warehouse/sibling.duckdb")
    assert manifest.tables[0].columns[0].synonyms == ("venta", "id")
    assert manifest.tables[0].columns[1].lookupable is False
    assert manifest.relationships[0].from_ == "sales.region"
    assert manifest.relationships[0].to == "regions.region"


@pytest.mark.parametrize(
    "name",
    ["duckdb_tables", "duckdb_views", "information_schema", "pg_catalog", "sqlite_master"],
)
def test_system_catalog_tables_are_rejected(name: str) -> None:
    document = manifest_document()
    document["tables"] = [
        {
            "name": name,
            "description": "hidden catalog",
            "columns": [{"name": "x", "type": "VARCHAR", "description": "x"}],
        }
    ]
    document["relationships"] = []

    with pytest.raises(ValidationError, match="reserved"):
        LakehouseManifest.model_validate(document)


def test_duplicate_tables_are_rejected_case_insensitively() -> None:
    document = manifest_document()
    tables = list(document["tables"])  # type: ignore[arg-type]
    document["tables"] = [*tables, {**tables[0], "name": "SALES"}]

    with pytest.raises(ValidationError, match="duplicate table"):
        LakehouseManifest.model_validate(document)


def test_duplicate_columns_are_rejected_case_insensitively() -> None:
    document = manifest_document()
    table = dict(document["tables"][0])  # type: ignore[index]
    columns = list(table["columns"])
    table["columns"] = [*columns, {**columns[0], "name": "SALE_ID"}]
    document["tables"] = [table, document["tables"][1]]  # type: ignore[index]

    with pytest.raises(ValidationError, match="duplicate column"):
        LakehouseManifest.model_validate(document)


def test_relationships_must_resolve_to_documented_columns() -> None:
    document = manifest_document(relationships=[{"from": "sales.missing", "to": "regions.region"}])

    with pytest.raises(ValidationError, match="relationship"):
        LakehouseManifest.model_validate(document)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("duckdb_file", "/absolute/warehouse.duckdb", "relative"),
        ("duckdb_file", r"C:\absolute\warehouse.duckdb", "relative"),
        ("duckdb_file", r"\\server\share\warehouse.duckdb", "relative"),
        ("duckdb_file", "../escape.duckdb", "escape"),
        ("duckdb_file", r"..\escape.duckdb", "escape"),
        ("duckdb_file", "warehouse/../../escape.duckdb", "escape"),
        ("sha256", "not-a-digest", "sha256"),
        ("schema", "sqlagent.lakehouse-manifest/v2", "schema"),
        ("tables", [], "tables"),
        ("name", "", "name"),
    ],
)
def test_invalid_fields_are_rejected(field: str, value: object, message: str) -> None:
    document = manifest_document(**{field: value})

    with pytest.raises(ValidationError, match=message):
        LakehouseManifest.model_validate(document)


def test_sha256_is_normalised_to_lowercase() -> None:
    document = manifest_document(sha256="A" * 64)

    assert LakehouseManifest.model_validate(document).sha256 == "a" * 64


def test_load_manifest_returns_validated_model(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest_document()), encoding="utf-8")

    manifest = load_manifest(path)

    assert manifest.name == "sibling-lakehouse"
    assert manifest.duckdb_file == Path("warehouse/sibling.duckdb")


def test_load_manifest_maps_io_and_json_errors_to_config_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ConfigError, match="cannot read"):
        load_manifest(missing)

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot parse"):
        load_manifest(broken)

    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(manifest_document(schema="wrong")), encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid lakehouse manifest"):
        load_manifest(invalid)
