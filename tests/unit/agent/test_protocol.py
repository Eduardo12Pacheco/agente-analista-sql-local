"""Constrained JSON action protocol (S10/D4)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from sqlagent.application.agent.protocol import (
    GENERATE_SCHEMA,
    NARRATE_SCHEMA,
    GenerateAction,
    NarrateOutput,
    parse_action,
    parse_narration,
)
from sqlagent.domain.errors import LLMProtocolError


def _action(**overrides: object) -> GenerateAction:
    payload: dict[str, object] = {
        "plan": ["count rows"],
        "action": "final_sql",
        "sql": "SELECT COUNT(*) AS n FROM tenders",
    }
    payload.update(overrides)
    return GenerateAction.model_validate(payload)


def test_final_sql_requires_non_empty_sql() -> None:
    with pytest.raises(ValidationError):
        _action(sql="   ")
    with pytest.raises(ValidationError):
        _action(sql=None)
    assert _action().sql == "SELECT COUNT(*) AS n FROM tenders"


def test_lookup_values_requires_lookup() -> None:
    with pytest.raises(ValidationError):
        _action(action="lookup_values")
    action = _action(
        action="lookup_values",
        sql=None,
        lookup={"column": "buyers.buyer_name", "query": "iess"},
    )
    assert action.lookup is not None
    assert action.lookup.column == "buyers.buyer_name"


def test_clarify_and_refuse_require_message() -> None:
    for kind in ("clarify", "refuse"):
        with pytest.raises(ValidationError):
            _action(action=kind, sql=None)
    assert _action(action="clarify", sql=None, message="¿Qué monto?").message == "¿Qué monto?"
    assert _action(action="refuse", sql=None, message="Solo lectura.").action == "refuse"


def test_plan_is_bounded_and_steps_are_short() -> None:
    with pytest.raises(ValidationError):
        _action(plan=[])
    with pytest.raises(ValidationError):
        _action(plan=["x"] * 6)
    with pytest.raises(ValidationError):
        _action(plan=["x" * 161])
    assert _action(plan=["a", "b"]).plan == ["a", "b"]


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _action(delete_rows=True)


def test_json_schemas_are_deterministic_and_constrained() -> None:
    assert GenerateAction.model_json_schema() == GENERATE_SCHEMA
    assert GENERATE_SCHEMA["properties"]["action"]["enum"] == [
        "final_sql",
        "lookup_values",
        "clarify",
        "refuse",
    ]
    assert NarrateOutput.model_json_schema() == NARRATE_SCHEMA
    assert json.dumps(GENERATE_SCHEMA, sort_keys=True) == json.dumps(
        GenerateAction.model_json_schema(), sort_keys=True
    )


def test_parse_action_accepts_plain_and_fenced_json() -> None:
    payload = {
        "plan": ["count"],
        "action": "final_sql",
        "sql": "SELECT COUNT(*) AS n FROM tenders",
    }
    assert parse_action(json.dumps(payload)).sql == payload["sql"]
    fenced = f"```json\n{json.dumps(payload)}\n```"
    assert parse_action(fenced).action == "final_sql"
    prose = f"Here is the plan:\n{json.dumps(payload)}\nDone."
    assert parse_action(prose).sql == payload["sql"]


def test_parse_action_raises_typed_error_on_bad_content() -> None:
    for text in ("", "not json", '{"action": "final_sql"}', "{}", "```\n```"):
        with pytest.raises(LLMProtocolError):
            parse_action(text)


def test_parse_narration_accepts_only_the_answer_object() -> None:
    assert parse_narration('{"answer": "Hay 3 filas."}').answer == "Hay 3 filas."
    assert parse_narration('```json\n{"answer": "Found 3 rows."}\n```').answer == "Found 3 rows."
    with pytest.raises(LLMProtocolError):
        parse_narration('{"answer": ""}')
    with pytest.raises(LLMProtocolError):
        parse_narration('{"text": "wrong field"}')
