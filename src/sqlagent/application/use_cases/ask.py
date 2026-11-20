"""``AskQuestion`` use case with one-turn session memory (S13).

The agent is single-turn by design; this use case remembers the previous question
and its final SQL per session in an LRU(50) map so a follow-up ("and by
province?") can be resolved.  Evaluation calls it without a session id, which
disables memory and keeps runs independent.
"""

from __future__ import annotations

from collections import OrderedDict

from sqlagent.application.agent.events import EventSink
from sqlagent.application.agent.machine import AnalystAgent
from sqlagent.application.agent.state import TurnContext
from sqlagent.domain.models import AgentAnswer, Language, Status

DEFAULT_SESSION_CAPACITY = 50


class AskQuestion:
    """Execute a question through the agent, remembering the previous turn."""

    def __init__(
        self,
        agent: AnalystAgent,
        *,
        capacity: int = DEFAULT_SESSION_CAPACITY,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._agent = agent
        self._capacity = capacity
        self._turns: OrderedDict[str, TurnContext] = OrderedDict()

    @property
    def sessions(self) -> tuple[str, ...]:
        """Session ids in least-recently-used order (diagnostics/tests)."""

        return tuple(self._turns)

    def execute(
        self,
        question: str,
        session_id: str | None = None,
        *,
        language: Language | None = None,
        sink: EventSink | None = None,
    ) -> AgentAnswer:
        """Answer ``question``, optionally continuing ``session_id``'s last turn."""

        history = self._turns.get(session_id) if session_id else None
        answer = self._agent.run(question, language=language, history=history, sink=sink)
        if session_id and answer.status is Status.OK and answer.sql:
            self._remember(session_id, TurnContext(question=question, sql=answer.sql))
        return answer

    def _remember(self, session_id: str, turn: TurnContext) -> None:
        self._turns[session_id] = turn
        self._turns.move_to_end(session_id)
        while len(self._turns) > self._capacity:
            self._turns.popitem(last=False)


__all__ = ["DEFAULT_SESSION_CAPACITY", "AskQuestion"]
