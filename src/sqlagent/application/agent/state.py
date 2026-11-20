"""Agent phases and bounds (S9/D5).

The state machine is a small, explicit handler table keyed by :class:`Phase`.
Terminal phases never transition further, which is what makes termination
bounded and independent of the model's output.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

MAX_QUESTION_CHARS = 600
MAX_LLM_CALLS = 12
MAX_PLAN_STEPS = 5
MAX_PLAN_STEP_CHARS = 160


@dataclass(frozen=True, slots=True)
class TurnContext:
    """The previous question and its final SQL for one-turn follow-ups (S13)."""

    question: str
    sql: str


class Phase(StrEnum):
    """Every non-terminal and terminal phase of one agent run (D5)."""

    UNDERSTAND = "UNDERSTAND"
    RETRIEVE = "RETRIEVE"
    GENERATE = "GENERATE"
    TOOL = "TOOL"
    VALIDATE = "VALIDATE"
    EXECUTE = "EXECUTE"
    REPAIR = "REPAIR"
    CHART = "CHART"
    NARRATE = "NARRATE"
    DONE = "DONE"
    CLARIFY = "CLARIFY"
    REFUSE = "REFUSE"
    FAILED = "FAILED"


TERMINAL_PHASES: frozenset[Phase] = frozenset(
    {Phase.DONE, Phase.CLARIFY, Phase.REFUSE, Phase.FAILED}
)


__all__ = [
    "MAX_LLM_CALLS",
    "MAX_PLAN_STEPS",
    "MAX_PLAN_STEP_CHARS",
    "MAX_QUESTION_CHARS",
    "TERMINAL_PHASES",
    "Phase",
    "TurnContext",
]
