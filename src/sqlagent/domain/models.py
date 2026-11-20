"""Domain models shared by the agent, evaluation engine and interfaces.

Every model is a frozen, slotted dataclass so values are immutable, safe to share
between threads and cheap to construct.  Models carry data only; behaviour lives
in domain services (chart chooser, SQL policy, equivalence, ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

ChartKind = Literal["none", "kpi", "line", "bar", "hbar", "scatter"]
AttemptKind = Literal["generate", "repair"]


class Language(StrEnum):
    """Question/answer language supported by the agent."""

    ES = "es"
    EN = "en"


class Status(StrEnum):
    """Terminal status of an agent answer (S12)."""

    OK = "ok"
    CLARIFICATION = "clarification"
    REFUSED = "refused"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Prompt/completion token counts for one or more LLM calls."""

    prompt: int = 0
    completion: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt=self.prompt + other.prompt,
            completion=self.completion + other.completion,
        )

    @property
    def total(self) -> int:
        return self.prompt + self.completion


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    """One result column: name plus the DuckDB type string."""

    name: str
    type: str


@dataclass(frozen=True, slots=True)
class QueryResult:
    """A bounded SQL result set (at most ``max_rows`` rows)."""

    columns: tuple[ColumnInfo, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    truncated: bool = False
    elapsed_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class ChartSpec:
    """Chart selected for a result set (D21); ``reason`` is a stable UI key."""

    kind: ChartKind
    x: str | None = None
    y: tuple[str, ...] = ()
    series: str | None = None
    title: str = ""
    reason: str = ""
    truncated_categories: bool = False


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One SQL generation or repair attempt recorded in the trace."""

    kind: AttemptKind
    sql: str
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PhaseTiming:
    """Wall-clock duration of one agent phase."""

    phase: str
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class Trace:
    """Observable execution trace attached to every answer (S12)."""

    phases: tuple[PhaseTiming, ...] = ()
    attempts: tuple[AttemptRecord, ...] = ()
    retrieved_tables: tuple[str, ...] = ()
    tool_calls: int = 0
    guardrail_events: tuple[str, ...] = ()
    injection_flags: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    llm_calls: int = 0


@dataclass(frozen=True, slots=True)
class AgentAnswer:
    """User-facing answer with SQL, result, chart and trace (S12)."""

    status: Status
    language: Language
    text: str
    sql: str | None = None
    result: QueryResult | None = None
    chart: ChartSpec | None = None
    trace: Trace = field(default_factory=Trace)
