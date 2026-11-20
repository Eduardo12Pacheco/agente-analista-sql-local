"""Constrained JSON action protocol for GENERATE/REPAIR (S10/D4).

The model never gets provider-native tool calling: every backend returns one
flat JSON object validated by :class:`GenerateAction`.  ``parse_action`` is
deliberately tolerant about markdown fences and surrounding prose (small models
add them) but strict about the schema, which is also what ``format`` receives.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from sqlagent.application.agent.state import MAX_PLAN_STEP_CHARS, MAX_PLAN_STEPS
from sqlagent.domain.errors import LLMProtocolError

ActionKind = Literal["final_sql", "lookup_values", "clarify", "refuse"]


class LookupRequest(BaseModel):
    """A whitelisted value lookup requested by the model (S8)."""

    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1)
    query: str = Field(min_length=1)


class GenerateAction(BaseModel):
    """The only shape a GENERATE/REPAIR response may take (D4/S10)."""

    model_config = ConfigDict(extra="forbid")

    plan: list[str] = Field(min_length=1, max_length=MAX_PLAN_STEPS)
    action: ActionKind
    sql: str | None = None
    lookup: LookupRequest | None = None
    message: str | None = None

    @model_validator(mode="after")
    def _check_action_payload(self) -> GenerateAction:
        if any(len(step) > MAX_PLAN_STEP_CHARS for step in self.plan):
            raise ValueError(f"each plan step must be <= {MAX_PLAN_STEP_CHARS} characters")
        if self.action == "final_sql":
            if self.sql is None or not self.sql.strip():
                raise ValueError("action final_sql requires a non-empty sql")
        elif self.action == "lookup_values":
            if self.lookup is None:
                raise ValueError("action lookup_values requires lookup")
        elif self.message is None or not self.message.strip():
            raise ValueError(f"action {self.action} requires a non-empty message")
        return self


class NarrateOutput(BaseModel):
    """The narration response: one answer string in the question language (D22)."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)


GENERATE_SCHEMA: dict[str, Any] = GenerateAction.model_json_schema()
NARRATE_SCHEMA: dict[str, Any] = NarrateOutput.model_json_schema()


_MIN_FENCED_LINES = 3


def _extract_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= _MIN_FENCED_LINES and lines[-1].strip().startswith("```"):
            stripped = "\n".join(lines[1:-1]).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        raise LLMProtocolError("response did not contain a JSON object")
    return stripped[start : end + 1]


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(_extract_object(text))
    except json.JSONDecodeError as exc:
        raise LLMProtocolError(f"response is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise LLMProtocolError("response JSON must be an object")
    return value


def parse_action(text: str) -> GenerateAction:
    """Parse one model response into an action or raise ``LLMProtocolError``."""

    payload = _parse_json_object(text)
    try:
        return GenerateAction.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        raise LLMProtocolError(f"invalid action at {location or 'root'}: {first['msg']}") from exc


def parse_narration(text: str) -> NarrateOutput:
    """Parse the narration response or raise ``LLMProtocolError``."""

    payload = _parse_json_object(text)
    try:
        return NarrateOutput.model_validate(payload)
    except ValidationError as exc:
        raise LLMProtocolError(f"invalid narration: {exc.errors()[0]['msg']}") from exc


__all__ = [
    "GENERATE_SCHEMA",
    "NARRATE_SCHEMA",
    "ActionKind",
    "GenerateAction",
    "LookupRequest",
    "NarrateOutput",
    "parse_action",
    "parse_narration",
]
