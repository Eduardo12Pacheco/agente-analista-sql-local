"""Semantic layer derived from an external lakehouse manifest (S31/D28).

An external warehouse has no bundled metrics, glossary or few-shots: the
manifest is the only documentation, so the adapter maps it mechanically into the
same :class:`SemanticLayer` dataclasses the bundled YAML repository produces.
"""

from __future__ import annotations

from sqlagent.adapters.warehouse.lakehouse import LakehouseManifest
from sqlagent.domain.semantic import (
    Relationship,
    SemanticColumn,
    SemanticLayer,
    SemanticTable,
)


class ManifestSemanticLayerRepository:
    """Build a semantic layer from a validated lakehouse manifest."""

    def __init__(self, manifest: LakehouseManifest) -> None:
        self.manifest = manifest

    def load(self) -> SemanticLayer:
        """Return the semantic layer; metrics and glossary are empty by design."""

        tables = tuple(
            SemanticTable(
                name=table.name,
                description_en=table.description,
                description_es=table.description,
                columns=tuple(
                    SemanticColumn(
                        name=column.name,
                        type=column.type,
                        description_en=column.description,
                        description_es=column.description,
                        synonyms=column.synonyms,
                        lookupable=column.lookupable,
                        samples=column.samples,
                    )
                    for column in table.columns
                ),
            )
            for table in self.manifest.tables
        )
        relationships = tuple(
            Relationship(
                from_=relationship.from_,
                to=relationship.to,
                on=f"{relationship.from_} = {relationship.to}",
            )
            for relationship in self.manifest.relationships
        )
        return SemanticLayer(tables=tables, relationships=relationships)


__all__ = ["ManifestSemanticLayerRepository"]
