"""Termination property: arbitrary model output stays bounded (S9/T7)."""

from __future__ import annotations

from hypothesis import HealthCheck, given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from sqlagent.adapters.llm.scripted import ScriptedLLM
from sqlagent.application.agent.state import MAX_LLM_CALLS
from sqlagent.domain.models import Status


@hypothesis_settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(st.text(max_size=200))
def test_arbitrary_model_output_always_terminates(make_agent, payload: str) -> None:
    llm = ScriptedLLM(lambda request: payload)
    answer = make_agent(llm).run("How many tenders are there?")

    assert answer.status in set(Status)
    assert len(llm.calls) <= MAX_LLM_CALLS
    assert answer.trace.llm_calls == len(llm.calls)
    assert answer.trace.llm_calls <= MAX_LLM_CALLS
