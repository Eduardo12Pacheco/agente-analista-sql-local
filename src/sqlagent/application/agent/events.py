"""Agent progress events for CLI and web observers (D24/S29).

Events are frozen data records, so a slow or failing sink can never change an
answer.  ``NullSink`` is the null-object implementation used by tests and the
evaluation harness.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from sqlagent.application.agent.state import Phase


class EventKind(StrEnum):
    """Kinds emitted by the state machine, in typical order."""

    PHASE = "phase"
    RETRIEVAL = "retrieval"
    ATTEMPT = "attempt"
    SQL = "sql"
    RESULT = "result"
    CHART = "chart"
    ANSWER = "answer"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """One observable step of a run; ``payload`` carries small JSON-safe values."""

    kind: EventKind
    phase: Phase | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class EventSink(Protocol):
    """Observer of agent events (Observer pattern, D24)."""

    def emit(self, event: AgentEvent) -> None:
        """Receive one event; implementations must not raise."""


class NullSink:
    """A sink that discards every event (tests, evaluation)."""

    def emit(self, event: AgentEvent) -> None:
        return None


__all__ = ["AgentEvent", "EventKind", "EventSink", "NullSink"]
