"""Application ports: the hexagonal boundary every adapter implements.

The definitions are protocol/typed-dataclass only and import nothing from the
adapter layer, keeping the dependency direction ``adapters -> application ->
domain`` (S32).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from sqlagent.domain.models import ColumnInfo, QueryResult
from sqlagent.domain.semantic import SemanticLayer
from sqlagent.domain.sql_policy import ValidatedQuery


@dataclass(frozen=True, slots=True)
class Catalog:
    """Tables and columns of a warehouse, in ordinal order."""

    tables: Mapping[str, tuple[ColumnInfo, ...]] = field(default_factory=dict)

    def table_names(self) -> frozenset[str]:
        return frozenset(self.tables)

    def columns(self, table: str) -> tuple[ColumnInfo, ...]:
        return self.tables.get(table.lower(), ())


@dataclass(frozen=True, slots=True)
class WarehouseInfo:
    """Human/CLI-facing warehouse metadata (S5, D9)."""

    path: Path
    manifest_sha256: str
    tables: Mapping[str, int]
    source_url: str
    license: str
    attribution: str = ""
    built_at: str | None = None


@dataclass(frozen=True, slots=True)
class WarehouseLimits:
    """Resource limits applied to the read-only DuckDB connection (D15)."""

    max_rows: int = 1_000
    ui_rows: int = 200
    query_timeout_s: float = 20.0
    memory_limit: str = "2GB"
    threads: int = 4


@runtime_checkable
class WarehousePort(Protocol):
    """Read-only warehouse used by the agent and the evaluation harness."""

    def execute(self, query: ValidatedQuery) -> QueryResult:
        """Execute a validated query, honouring the row cap and watchdog."""

    def lookup_values(self, ref: str, query: str, k: int = 5) -> list[str]:
        """Resolve a colloquial value against one whitelisted text column."""

    def catalog(self) -> Catalog:
        """Return the warehouse catalog (queried before the lockdown)."""

    def info(self) -> WarehouseInfo:
        """Return manifest metadata and row counts."""


@runtime_checkable
class SemanticLayerRepository(Protocol):
    """Load the documented tables, metrics and glossary (S6)."""

    def load(self) -> SemanticLayer:
        """Return the validated semantic layer."""
