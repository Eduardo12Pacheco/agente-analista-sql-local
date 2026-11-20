"""Semantic-layer dataclasses (D13).

The YAML adapter in T5 maps ``resources/semantic_layer.yaml`` onto these frozen
dataclasses.  Lookups are case-insensitive so SQL identifiers and colloquial
references can be resolved without leaking adapter details into the domain.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemanticColumn:
    """A documented warehouse column (D13)."""

    name: str
    type: str
    description_en: str
    description_es: str
    synonyms: tuple[str, ...] = ()
    lookupable: bool = False
    samples: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticTable:
    """A documented warehouse table and its columns (D13)."""

    name: str
    description_en: str
    description_es: str
    synonyms: tuple[str, ...] = ()
    columns: tuple[SemanticColumn, ...] = ()


@dataclass(frozen=True, slots=True)
class Metric:
    """A named, reusable aggregation over one or more tables (D13)."""

    name: str
    expression_sql: str
    description_en: str
    description_es: str
    synonyms: tuple[str, ...] = ()
    tables: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Relationship:
    """A documented join path between two columns (D13)."""

    from_: str
    to: str
    on: str


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    """Bilingual glossary terms with one shared explanation (D13/S6)."""

    terms: tuple[str, ...]
    meaning: str


@dataclass(frozen=True, slots=True)
class SemanticLayer:
    """The complete semantic layer served to retrieval and prompts."""

    tables: tuple[SemanticTable, ...] = ()
    metrics: tuple[Metric, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    glossary: tuple[GlossaryEntry, ...] = ()
    data_quirks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        seen_tables: set[str] = set()
        for table in self.tables:
            key = table.name.casefold()
            if key in seen_tables:
                raise ValueError(f"duplicate table: {table.name}")
            seen_tables.add(key)
            seen_columns: set[str] = set()
            for column in table.columns:
                column_key = column.name.casefold()
                if column_key in seen_columns:
                    raise ValueError(f"duplicate column: {table.name}.{column.name}")
                seen_columns.add(column_key)

    def table(self, name: str) -> SemanticTable | None:
        """Return the table named ``name`` (case-insensitive) or ``None``."""

        needle = name.casefold()
        for table in self.tables:
            if table.name.casefold() == needle:
                return table
        return None

    def column(self, ref: str) -> SemanticColumn | None:
        """Resolve a ``table.column`` reference (case-insensitive) or ``None``."""

        table_name, separator, column_name = ref.partition(".")
        if not separator:
            return None
        table = self.table(table_name)
        if table is None:
            return None
        needle = column_name.casefold()
        for column in table.columns:
            if column.name.casefold() == needle:
                return column
        return None

    def lookupable_columns(self) -> tuple[str, ...]:
        """Return ``table.column`` refs for every lookupable column, in order."""

        return tuple(
            f"{table.name}.{column.name}"
            for table in self.tables
            for column in table.columns
            if column.lookupable
        )
