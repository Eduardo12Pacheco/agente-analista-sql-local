"""Semantic-layer dataclasses and lookup helpers."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from sqlagent.domain.semantic import (
    GlossaryEntry,
    Metric,
    Relationship,
    SemanticColumn,
    SemanticLayer,
    SemanticTable,
)

pytestmark = pytest.mark.unit


def _semantic_layer() -> SemanticLayer:
    tenders = SemanticTable(
        name="tenders",
        description_en="Contracting processes",
        description_es="Procesos de contratación",
        synonyms=("processes", "procesos"),
        columns=(
            SemanticColumn(
                name="tender_id",
                type="VARCHAR",
                description_en="Process identifier",
                description_es="Identificador del proceso",
                synonyms=("ocid",),
            ),
            SemanticColumn(
                name="procurement_type",
                type="VARCHAR",
                description_en="Procurement type",
                description_es="Tipo de contratación",
                synonyms=("modalidad",),
                lookupable=True,
                samples=("open", "direct"),
            ),
        ),
    )
    suppliers = SemanticTable(
        name="suppliers",
        description_en="Suppliers",
        description_es="Proveedores",
        columns=(
            SemanticColumn(
                name="supplier_name",
                type="VARCHAR",
                description_en="Supplier name",
                description_es="Nombre del proveedor",
                lookupable=True,
            ),
        ),
    )
    return SemanticLayer(
        tables=(tenders, suppliers),
        metrics=(
            Metric(
                name="tender_count",
                expression_sql="COUNT(*)",
                description_en="Number of tenders",
                description_es="Número de procesos",
                synonyms=("procesos",),
                tables=("tenders",),
            ),
        ),
        relationships=(
            Relationship(
                from_="tenders.buyer_id",
                to="buyers.buyer_id",
                on="tenders.buyer_id = buyers.buyer_id",
            ),
        ),
        glossary=(
            GlossaryEntry(terms=("subasta inversa", "reverse auction"), meaning="Auction modality"),
        ),
        data_quirks=("SIE planned amounts are NULL by policy",),
    )


def test_semantic_layer_lookups() -> None:
    layer = _semantic_layer()

    assert layer.table("tenders") is layer.tables[0]
    assert layer.table("TENDERS") is layer.tables[0]
    assert layer.table("missing") is None
    assert layer.column("tenders.tender_id") is layer.tables[0].columns[0]
    assert layer.column("TENDERS.TENDER_ID") is layer.tables[0].columns[0]
    assert layer.column("tenders.missing") is None
    assert layer.column("missing.tender_id") is None
    assert layer.column("tender_id") is None
    assert layer.lookupable_columns() == (
        "tenders.procurement_type",
        "suppliers.supplier_name",
    )
    assert layer.data_quirks == ("SIE planned amounts are NULL by policy",)


def test_semantic_layer_rejects_duplicate_table_and_column_names() -> None:
    table = SemanticTable(
        name="tenders",
        description_en="a",
        description_es="b",
        columns=(
            SemanticColumn(name="id", type="VARCHAR", description_en="a", description_es="b"),
        ),
    )
    with pytest.raises(ValueError, match="duplicate table"):
        SemanticLayer(tables=(table, table))

    duplicate_columns = SemanticTable(
        name="tenders",
        description_en="a",
        description_es="b",
        columns=(
            SemanticColumn(name="id", type="VARCHAR", description_en="a", description_es="b"),
            SemanticColumn(name="id", type="VARCHAR", description_en="a", description_es="b"),
        ),
    )
    with pytest.raises(ValueError, match="duplicate column"):
        SemanticLayer(tables=(duplicate_columns,))


@pytest.mark.parametrize(
    "model_class",
    [SemanticColumn, SemanticTable, Metric, Relationship, GlossaryEntry, SemanticLayer],
)
def test_semantic_dataclasses_are_frozen(model_class: type[Any]) -> None:
    assert dataclasses.is_dataclass(model_class)
    assert getattr(model_class, "__slots__", None) is not None
