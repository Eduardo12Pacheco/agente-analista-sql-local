"""Reusable contract suite for every ``LLMPort`` implementation (S20).

The suite runs the same behavioural assertions over the scripted fake, a
cassette replay, a recording decorator and the Ollama HTTP adapter with an
injected ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from sqlagent.adapters.llm.cassette import RecordingLLM, ReplayLLM, request_key
from sqlagent.adapters.llm.ollama import OllamaLLM
from sqlagent.adapters.llm.scripted import ScriptedLLM
from sqlagent.application.ports import (
    BackendInfo,
    LLMOptions,
    LLMPort,
    LLMRequest,
    LLMResponse,
)
from sqlagent.config import Settings
from sqlagent.domain.errors import CassetteMiss, LLMError
from sqlagent.domain.models import TokenUsage

CONTENT = '{"action": "final_sql", "sql": "SELECT COUNT(*) AS n FROM tenders"}'
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "sql": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["action"],
}
STANDARD_REQUEST = LLMRequest(
    messages=(
        {"role": "system", "content": "You are a DuckDB analyst. Return flat JSON."},
        {"role": "user", "content": "How many tenders are in the database?"},
    ),
    model="qwen3:8b",
    stage="generate",
    json_schema=SCHEMA,
    options=LLMOptions(),
    question_id="q001",
)

CHAT_REPLY = {
    "model": "qwen3:8b",
    "message": {"role": "assistant", "content": CONTENT},
    "prompt_eval_count": 100,
    "eval_count": 20,
    "total_duration": 1_000_000_000,
}


@dataclass
class Harness:
    """One backend plus backend-specific introspection hooks."""

    kind: str
    llm: LLMPort
    cassette_path: Path | None = None
    inner: ScriptedLLM | None = None
    payloads: list[dict[str, Any]] = field(default_factory=list)
    failing: LLMPort | None = None


def _ollama_harness(tmp_path: Path) -> Harness:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json=CHAT_REPLY)
        return httpx.Response(404, json={"error": "not found"})

    llm = OllamaLLM(Settings(), client=httpx.Client(transport=httpx.MockTransport(handler)))

    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    failing = OllamaLLM(
        Settings(),
        client=httpx.Client(transport=httpx.MockTransport(failing_handler)),
        sleep=lambda seconds: None,
    )
    return Harness(kind="ollama", llm=llm, payloads=payloads, failing=failing)


@pytest.fixture(params=["scripted", "replay", "recording", "ollama"])
def harness(request: pytest.FixtureRequest, tmp_path: Path) -> Harness:
    kind = str(request.param)
    if kind == "scripted":
        inner = ScriptedLLM([CONTENT, CONTENT])
        return Harness(
            kind=kind,
            llm=inner,
            inner=inner,
            failing=ScriptedLLM([LLMError("connection refused")]),
        )
    cassette_path = tmp_path / f"{kind}.jsonl"
    if kind == "recording":
        inner = ScriptedLLM([CONTENT, CONTENT])
        return Harness(
            kind=kind,
            llm=RecordingLLM(inner, cassette_path),
            cassette_path=cassette_path,
            inner=inner,
            failing=RecordingLLM(
                ScriptedLLM([LLMError("connection refused")]), tmp_path / "failing.jsonl"
            ),
        )
    if kind == "replay":
        seed = RecordingLLM(ScriptedLLM([CONTENT]), cassette_path)
        seed.complete(STANDARD_REQUEST)
        return Harness(
            kind=kind,
            llm=ReplayLLM(cassette_path),
            cassette_path=cassette_path,
            failing=ReplayLLM(tmp_path / "empty.jsonl"),
        )
    return _ollama_harness(tmp_path)


def test_returns_content_usage_and_latency(harness: Harness) -> None:
    response = harness.llm.complete(STANDARD_REQUEST)

    assert response.content == CONTENT
    assert isinstance(response, LLMResponse)
    assert isinstance(response.usage, TokenUsage)
    assert response.usage.prompt > 0
    assert response.usage.completion > 0
    assert isinstance(response.latency_ms, float)
    assert response.latency_ms >= 0
    assert response.backend in {"scripted", "replay", "ollama"}


def test_honours_json_schema_passthrough(harness: Harness) -> None:
    other_schema: dict[str, Any] = {"type": "string", "maxLength": 10}
    other_request = LLMRequest(
        messages=STANDARD_REQUEST.messages,
        model=STANDARD_REQUEST.model,
        stage="generate",
        json_schema=other_schema,
        options=STANDARD_REQUEST.options,
    )

    if harness.kind == "ollama":
        harness.llm.complete(STANDARD_REQUEST)
        assert harness.payloads[-1]["format"] == SCHEMA
        harness.llm.complete(other_request)
        assert harness.payloads[-1]["format"] == other_schema
        assert harness.payloads[-1]["messages"] == [
            {"role": "system", "content": "You are a DuckDB analyst. Return flat JSON."},
            {"role": "user", "content": "How many tenders are in the database?"},
        ]
    elif harness.kind in {"scripted", "recording"}:
        harness.llm.complete(STANDARD_REQUEST)
        seen = harness.inner.calls if harness.inner is not None else []
        assert seen[-1].json_schema == SCHEMA
        harness.llm.complete(other_request)
        assert seen[-1].json_schema == other_schema
    else:
        # Replay changes identity when the schema changes, proving it is part of
        # the key; the recorded schema still round-trips.
        assert harness.llm.complete(STANDARD_REQUEST).content == CONTENT
        with pytest.raises(CassetteMiss):
            harness.llm.complete(other_request)


def test_transport_failure_raises_llm_error(harness: Harness) -> None:
    assert harness.failing is not None
    with pytest.raises(LLMError):
        harness.failing.complete(STANDARD_REQUEST)


def test_request_key_is_deterministic_and_option_sensitive(harness: Harness) -> None:
    equal = LLMRequest(
        messages=STANDARD_REQUEST.messages,
        model=STANDARD_REQUEST.model,
        stage=STANDARD_REQUEST.stage,
        json_schema=STANDARD_REQUEST.json_schema,
        options=LLMOptions(temperature=0.0, seed=42),
        question_id="different-id-does-not-matter",
    )
    hotter = LLMRequest(
        messages=STANDARD_REQUEST.messages,
        model=STANDARD_REQUEST.model,
        stage=STANDARD_REQUEST.stage,
        json_schema=STANDARD_REQUEST.json_schema,
        options=LLMOptions(temperature=0.8, seed=42),
    )

    assert request_key(STANDARD_REQUEST) == request_key(equal)
    assert request_key(STANDARD_REQUEST) != request_key(hotter)


def test_describe_reports_a_backend(harness: Harness) -> None:
    info = harness.llm.describe()

    assert isinstance(info, BackendInfo)
    assert info.backend in {"scripted", "recording", "replay", "ollama"}
    assert isinstance(info.model, str)
