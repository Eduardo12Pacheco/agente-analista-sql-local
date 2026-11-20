"""Application ports: the hexagonal boundary every adapter implements.

The definitions are protocol/typed-dataclass only and import nothing from the
adapter layer, keeping the dependency direction ``adapters -> application ->
domain`` (S32).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from sqlagent.application.evaluation.benchmark import Benchmark
from sqlagent.domain.models import ColumnInfo, QueryResult, TokenUsage
from sqlagent.domain.semantic import SemanticLayer
from sqlagent.domain.sql_policy import ValidatedQuery

LLMStage = Literal["generate", "repair", "narrate"]


@dataclass(frozen=True, slots=True)
class LLMOptions:
    """Sampling options sent with every LLM call (D12/D18)."""

    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 8192
    num_predict: int = 768


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """One backend-independent completion request.

    ``question_id`` is cassette metadata only and deliberately excluded from the
    request key: re-recording the same prompt for a different benchmark item must
    not change its identity (D18).
    """

    messages: tuple[Mapping[str, str], ...]
    model: str
    stage: LLMStage = "generate"
    json_schema: Mapping[str, Any] | None = None
    options: LLMOptions = field(default_factory=LLMOptions)
    question_id: str | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Content plus the usage and latency metadata the trace needs (S12)."""

    content: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    model: str = ""
    model_digest: str | None = None
    backend: str = ""
    stage: str = ""


@dataclass(frozen=True, slots=True)
class BackendInfo:
    """Describe the configured backend for ``doctor`` and the web status pill."""

    backend: str
    model: str
    digest: str | None = None
    available: bool = True
    detail: str = ""


@runtime_checkable
class LLMPort(Protocol):
    """A completion backend usable by the agent and evaluation harness (S20)."""

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return one completion or raise an ``LLMError`` subclass."""

    def describe(self) -> BackendInfo:
        """Return stable backend/model metadata without requiring a call."""


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


@runtime_checkable
class BenchmarkRepository(Protocol):
    """Load one versioned benchmark and its gold SQL (S23)."""

    def load(self, version: str = "v1") -> Benchmark:
        """Return the validated benchmark or raise ``ConfigError``."""
