"""The committed semantic layer must match the materialised warehouse exactly (S6)."""

from __future__ import annotations

import pytest

from sqlagent.adapters.semantic.yaml_repository import YamlSemanticLayerRepository
from sqlagent.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from sqlagent.adapters.warehouse.materialize import ensure_warehouse
from sqlagent.application.agent.tools import LookupValuesTool
from sqlagent.application.ports import Catalog
from sqlagent.config import Settings
from sqlagent.domain.semantic import SemanticLayer

pytestmark = pytest.mark.integration

EXPECTED_LOOKUPABLE = frozenset(
    {
        "buyers.buyer_name",
        "buyers.province",
        "buyers.canton",
        "suppliers.supplier_name",
        "suppliers.province",
        "tender_items.cpc_description",
        "tenders.procurement_type",
    }
)

EXPECTED_RELATIONSHIPS = frozenset(
    {
        ("tenders.buyer_id", "buyers.buyer_id"),
        ("awards.tender_id", "tenders.tender_id"),
        ("awards.supplier_id", "suppliers.supplier_id"),
        ("contracts.tender_id", "tenders.tender_id"),
        ("tender_items.tender_id", "tenders.tender_id"),
    }
)

LOW_CARDINALITY_COLUMNS = (
    "buyers.province",
    "suppliers.province",
    "suppliers.supplier_kind",
    "tenders.procurement_method",
    "tenders.procurement_type",
    "tenders.category",
    "tenders.status",
    "awards.status",
    "contracts.status",
)


@pytest.fixture(scope="module")
def layer() -> SemanticLayer:
    return YamlSemanticLayerRepository().load()


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> DuckDbWarehouse:
    data_dir = tmp_path_factory.mktemp("semantic-sync")
    path = ensure_warehouse(Settings(data_dir=data_dir))
    adapter = DuckDbWarehouse(path)
    try:
        yield adapter
    finally:
        adapter.close()


@pytest.fixture(scope="module")
def catalog(warehouse: DuckDbWarehouse) -> Catalog:
    return warehouse.catalog()


def test_tables_and_columns_match_the_live_schema(layer: SemanticLayer, catalog: Catalog) -> None:
    assert {table.name for table in layer.tables} == set(catalog.tables)
    for table in layer.tables:
        documented = {column.name.casefold(): column.type for column in table.columns}
        live = {column.name.casefold(): column.type for column in catalog.columns(table.name)}
        assert documented == live, table.name


def test_every_table_and_column_has_bilingual_descriptions(layer: SemanticLayer) -> None:
    for table in layer.tables:
        assert table.description_en.strip()
        assert table.description_es.strip()
        for column in table.columns:
            assert column.description_en.strip(), f"{table.name}.{column.name}"
            assert column.description_es.strip(), f"{table.name}.{column.name}"


def test_lookupable_columns_are_exactly_the_whitelist(layer: SemanticLayer) -> None:
    assert frozenset(layer.lookupable_columns()) == EXPECTED_LOOKUPABLE


def test_relationships_are_the_declared_foreign_keys(
    layer: SemanticLayer, catalog: Catalog
) -> None:
    relationships = {(item.from_, item.to) for item in layer.relationships}
    assert relationships == EXPECTED_RELATIONSHIPS
    for relationship in layer.relationships:
        assert relationship.on.strip()
        source_table, source_column = relationship.from_.split(".")
        target_table, target_column = relationship.to.split(".")
        assert source_table in catalog.tables
        assert target_table in catalog.tables
        assert source_column in {column.name for column in catalog.columns(source_table)}
        assert target_column in {column.name for column in catalog.columns(target_table)}


def test_metrics_are_documented_and_reference_real_tables(layer: SemanticLayer) -> None:
    names = [metric.name for metric in layer.metrics]
    assert len(layer.metrics) >= 8
    assert len(names) == len(set(names))
    for metric in layer.metrics:
        assert metric.expression_sql.strip()
        assert metric.description_en.strip()
        assert metric.description_es.strip()
        assert metric.tables
        for table in metric.tables:
            assert layer.table(table) is not None


def test_low_cardinality_columns_have_categorical_samples(layer: SemanticLayer) -> None:
    for ref in LOW_CARDINALITY_COLUMNS:
        column = layer.column(ref)
        assert column is not None
        assert column.samples, ref


def test_glossary_and_quirks_meet_the_bilingual_contract(layer: SemanticLayer) -> None:
    assert len(layer.glossary) >= 20
    for entry in layer.glossary:
        assert entry.terms
        assert entry.meaning.strip()
    assert len(layer.data_quirks) >= 5
    assert all(quirk.strip() for quirk in layer.data_quirks)


def test_lookup_values_resolves_known_entities_against_real_data(
    warehouse: DuckDbWarehouse, layer: SemanticLayer
) -> None:
    tool = LookupValuesTool(warehouse, layer)

    iess = tool.run("buyers.buyer_name", "iess seguridad social")
    assert iess.ok is True
    assert iess.values[0] == "INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL"
    assert iess.block.startswith("<<DATA nonce=")

    guayas = tool.run("buyers.province", "guayas")
    assert guayas.ok is True
    assert guayas.values[0] == "GUAYAS"

    rejected = tool.run("awards.amount_usd", "1000")
    assert rejected.ok is False
    assert rejected.error is not None
