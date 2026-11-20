"""Unit tests for the deterministic scripted backend (D17)."""

from __future__ import annotations

import pytest

from sqlagent.adapters.llm.scripted import ScriptedLLM
from sqlagent.application.ports import LLMOptions, LLMRequest, LLMResponse
from sqlagent.domain.errors import LLMError
from sqlagent.domain.models import TokenUsage


def make_request(stage: str = "generate") -> LLMRequest:
    return LLMRequest(
        messages=(
            {"role": "system", "content": "You answer with flat JSON."},
            {"role": "user", "content": "How many tenders are there?"},
        ),
        model="qwen3:8b",
        stage=stage,  # type: ignore[arg-type]
        options=LLMOptions(seed=7),
        question_id="q001",
    )


def test_sequence_returns_content_and_records_requests() -> None:
    llm = ScriptedLLM(['{"action": "final_sql"}', '{"answer": "ok"}'])

    first = llm.complete(make_request())
    second = llm.complete(make_request(stage="narrate"))

    assert first.content == '{"action": "final_sql"}'
    assert second.content == '{"answer": "ok"}'
    assert first.backend == "scripted"
    assert first.stage == "generate"
    assert first.usage.prompt > 0
    assert first.usage.completion > 0
    assert first.latency_ms >= 0
    assert [call.stage for call in llm.calls] == ["generate", "narrate"]
    assert llm.calls[0].question_id == "q001"


def test_callable_responder_receives_the_request() -> None:
    seen: list[LLMRequest] = []

    def responder(request: LLMRequest) -> str:
        seen.append(request)
        return f"stage={request.stage}"

    llm = ScriptedLLM(responder)
    response = llm.complete(make_request("repair"))

    assert response.content == "stage=repair"
    assert seen[0].stage == "repair"


def test_response_instance_is_returned_unchanged() -> None:
    canned = LLMResponse(
        content="canned",
        usage=TokenUsage(prompt=3, completion=2),
        latency_ms=12.5,
        model="m",
        backend="custom",
    )
    assert ScriptedLLM([canned]).complete(make_request()) is canned


def test_exception_instances_are_raised() -> None:
    llm = ScriptedLLM([LLMError("boom")])

    with pytest.raises(LLMError, match="boom"):
        llm.complete(make_request())


def test_exhausted_script_raises_llm_error() -> None:
    llm = ScriptedLLM(["only one"])
    llm.complete(make_request())

    with pytest.raises(LLMError, match="exhausted"):
        llm.complete(make_request())


def test_describe_reports_scripted_backend() -> None:
    info = ScriptedLLM(["x"], model="fake", digest="abc").describe()

    assert info.backend == "scripted"
    assert info.model == "fake"
    assert info.digest == "abc"
    assert info.available is True
