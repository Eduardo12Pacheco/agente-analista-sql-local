"""SSE transport and the in-memory run/answer store (D24).

The agent runs in a worker thread; its event sink marshals small, already-rendered
HTML fragments into the event loop with ``call_soon_threadsafe`` and the SSE
endpoint drains them.  Pending runs and finished answers live in a bounded
LRU+TTL store so a long-lived server cannot leak memory.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from queue import Queue, SimpleQueue
from typing import Final

from sqlagent.application.agent.events import AgentEvent, EventKind
from sqlagent.domain.models import AgentAnswer, Language

RUN_TTL_SECONDS: Final = 30 * 60
RUN_CAPACITY: Final = 100

SSE_EVENT_NAMES: Final[dict[EventKind, str]] = {
    EventKind.PHASE: "phase",
    EventKind.RETRIEVAL: "retrieval",
    EventKind.SQL: "sql",
    EventKind.RESULT: "result",
    EventKind.CHART: "chart",
    EventKind.ERROR: "error",
}

type SseItem = tuple[str, str]


def format_sse(event: str, data: str) -> str:
    """Format one SSE frame; every line of ``data`` gets its ``data:`` prefix."""

    lines = data.splitlines() or [""]
    payload = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event}\n{payload}\n\n"


@dataclass
class RunRecord:
    """One in-flight or finished chat request."""

    id: str
    question: str
    language: Language | None
    queue: Queue[SseItem | None] = field(default_factory=Queue)
    answer: AgentAnswer | None = None
    created_at: float = field(default_factory=time.monotonic)
    ui_language: str = "es"
    extras: dict[str, object] = field(default_factory=dict)

    def expired(self, now: float) -> bool:
        return now - self.created_at > RUN_TTL_SECONDS


class RunStore:
    """Bounded LRU store with a TTL for runs and their answers."""

    def __init__(self, capacity: int = RUN_CAPACITY) -> None:
        self._capacity = capacity
        self._runs: OrderedDict[str, RunRecord] = OrderedDict()

    def create(
        self,
        question: str,
        language: Language | None,
        ui_language: str = "es",
    ) -> RunRecord:
        self._purge()
        record = RunRecord(
            id=uuid.uuid4().hex[:16],
            question=question,
            language=language,
            ui_language=ui_language,
        )
        self._runs[record.id] = record
        self._runs.move_to_end(record.id)
        while len(self._runs) > self._capacity:
            self._runs.popitem(last=False)
        return record

    def get(self, run_id: str) -> RunRecord | None:
        self._purge()
        record = self._runs.get(run_id)
        if record is not None:
            self._runs.move_to_end(run_id)
        return record

    def complete(self, run_id: str, answer: AgentAnswer) -> None:
        record = self._runs.get(run_id)
        if record is not None:
            record.answer = answer

    def clear(self) -> None:
        self._runs.clear()

    def __len__(self) -> int:
        return len(self._runs)

    def _purge(self) -> None:
        now = time.monotonic()
        stale = [run_id for run_id, run in self._runs.items() if run.expired(now)]
        for run_id in stale:
            self._runs.pop(run_id, None)


class ThreadEventSink:
    """Forward agent events from the worker thread into a thread-safe queue.

    ``ANSWER`` and ``DONE`` are suppressed because the route emits them once the
    final answer is available (the agent emits them conditionally and without the
    rendered payload the browser needs).  A plain :class:`queue.Queue` is used so
    the producer never needs the asyncio loop; the SSE endpoint drains it from a
    worker thread.
    """

    def __init__(
        self,
        queue: Queue[SseItem | None],
        render: Callable[[str, AgentEvent], str],
    ) -> None:
        self._queue = queue
        self._render = render

    def emit(self, event: AgentEvent) -> None:
        name = SSE_EVENT_NAMES.get(event.kind)
        if name is None:
            return
        try:
            data = self._render(name, event)
        except Exception:  # a rendering bug must never break the agent run
            return
        self._queue.put((name, data))


__all__ = [
    "RUN_CAPACITY",
    "RUN_TTL_SECONDS",
    "SSE_EVENT_NAMES",
    "RunRecord",
    "RunStore",
    "SimpleQueue",
    "SseItem",
    "ThreadEventSink",
    "format_sse",
]
