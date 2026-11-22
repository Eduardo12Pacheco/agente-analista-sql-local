"""Unit tests for the Ollama adapter using ``httpx.MockTransport`` (S21)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sqlagent import REPOSITORY_URL
from sqlagent.adapters.llm.ollama import OllamaLLM, is_loopback_url
from sqlagent.application.ports import LLMOptions, LLMRequest, LLMResponse
from sqlagent.config import Settings
from sqlagent.domain.errors import ConfigError, LLMError

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"action": {"type": "string"}, "sql": {"type": "string"}},
    "required": ["action"],
}
CHAT_REPLY = {
    "model": "qwen3:8b",
    "message": {"role": "assistant", "content": '{"action": "final_sql", "sql": "SELECT 1"}'},
    "prompt_eval_count": 123,
    "eval_count": 45,
    "total_duration": 2_500_000_000,
}


def request_for(model: str = "qwen3:8b", options: LLMOptions | None = None) -> LLMRequest:
    return LLMRequest(
        messages=(
            {"role": "system", "content": "Return flat JSON."},
            {"role": "user", "content": "How many tenders are there?"},
        ),
        model=model,
        stage="generate",
        json_schema=SCHEMA,
        options=options or LLMOptions(),
    )


def client_with(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_payload_contains_schema_seed_think_and_stream_options() -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=CHAT_REPLY)

    llm = OllamaLLM(Settings(), client=client_with(handler))
    response = llm.complete(request_for())

    payload = payloads[0]
    assert payload["model"] == "qwen3:8b"
    assert payload["format"] == SCHEMA
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["keep_alive"] == "30m"
    assert payload["options"] == {
        "temperature": 0.0,
        "seed": 42,
        "num_ctx": 8192,
        "num_predict": 768,
    }
    assert payload["messages"][0] == {"role": "system", "content": "Return flat JSON."}
    assert response.content == CHAT_REPLY["message"]["content"]
    assert response.usage.prompt == 123
    assert response.usage.completion == 45
    assert response.latency_ms == pytest.approx(2_500.0)
    assert response.model == "qwen3:8b"
    assert response.backend == "ollama"


def test_think_flag_is_only_sent_for_qwen3_models() -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={**CHAT_REPLY, "model": "qwen2.5-coder:7b"})

    llm = OllamaLLM(Settings(), client=client_with(handler))
    llm.complete(request_for(model="qwen2.5-coder:7b"))

    assert "think" not in payloads[0]


def test_schema_is_optional() -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=CHAT_REPLY)

    request = LLMRequest(
        messages=({"role": "user", "content": "hi"},),
        model="qwen3:8b",
        json_schema=None,
    )
    OllamaLLM(Settings(), client=client_with(handler)).complete(request)

    assert "format" not in payloads[0]


def test_retries_twice_on_connect_error_then_raises_with_docker_hint() -> None:
    calls: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    llm = OllamaLLM(
        Settings(),
        client=client_with(handler),
        sleep=sleeps.append,
    )

    with pytest.raises(LLMError) as excinfo:
        llm.complete(request_for())

    assert len(calls) == 3
    assert sleeps == [0.5, 1.5]
    message = str(excinfo.value)
    assert "olllama" not in message  # sanity: the hint is spelled correctly
    assert "scripts/ollama-docker.sh up" in message
    assert "scripts/ollama-docker.sh pull qwen3:8b" in message
    assert REPOSITORY_URL in message


def test_missing_model_404_names_the_pull_command() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'qwen3:8b' not found"})

    llm = OllamaLLM(Settings(), client=client_with(handler))

    with pytest.raises(LLMError) as excinfo:
        llm.complete(request_for())

    message = str(excinfo.value)
    assert "ollama pull qwen3:8b" in message
    assert "scripts/ollama-docker.sh pull qwen3:8b" in message


def test_http_error_and_non_json_response_raise_llm_error() -> None:
    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(LLMError, match="HTTP 500"):
        OllamaLLM(Settings(), client=client_with(server_error)).complete(request_for())

    def invalid_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(LLMError, match="non-JSON"):
        OllamaLLM(Settings(), client=client_with(invalid_json)).complete(request_for())


def test_non_loopback_url_requires_explicit_opt_in() -> None:
    settings = Settings(ollama_url="http://192.168.1.40:11434")
    with pytest.raises(ConfigError, match="not loopback"):
        OllamaLLM(settings)

    allowed = OllamaLLM(Settings(ollama_url="http://192.168.1.40:11434", allow_remote_llm=True))
    allowed.close()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:11434", True),
        ("http://localhost:11434", True),
        ("http://[::1]:11434", True),
        ("http://192.168.1.40:11434", False),
        ("https://ollama.example.com", False),
        ("not a url", False),
    ],
)
def test_is_loopback_url(url: str, expected: bool) -> None:
    assert is_loopback_url(url) is expected


def test_probe_reports_version_models_and_model_presence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.16"})
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "qwen3:8b", "digest": "sha256:aaa"},
                        {"name": "llama3:8b", "digest": "sha256:bbb"},
                    ]
                },
            )
        return httpx.Response(404)

    llm = OllamaLLM(
        Settings(model="qwen3:8b"),
        client=client_with(handler),
    )
    probe = llm.probe()

    assert probe.reachable is True
    assert probe.version == "0.40.16"
    assert probe.models == ("qwen3:8b", "llama3:8b")
    assert probe.model_present is True
    assert probe.detail == ""


def test_probe_reports_unreachable_and_missing_model() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    probe = OllamaLLM(Settings(), client=client_with(unreachable)).probe()
    assert probe.reachable is False
    assert "ConnectError" in probe.detail

    def no_models(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.16"})
        return httpx.Response(200, json={"models": []})

    probe = OllamaLLM(Settings(), client=client_with(no_models)).probe()
    assert probe.reachable is True
    assert probe.models == ()
    assert probe.model_present is False


def test_describe_uses_cached_digest_after_probe() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.16"})
        return httpx.Response(
            200, json={"models": [{"name": "qwen2.5-coder:7b", "digest": "sha256:abc"}]}
        )

    llm = OllamaLLM(Settings(), client=client_with(handler))
    before = llm.describe()
    assert before.backend == "ollama"
    assert before.digest is None

    llm.probe()
    assert llm.describe().digest == "sha256:abc"


def test_parse_without_total_duration_falls_back_to_wall_clock() -> None:
    body = {k: v for k, v in CHAT_REPLY.items() if k != "total_duration"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    response: LLMResponse = OllamaLLM(Settings(), client=client_with(handler)).complete(
        request_for()
    )
    assert response.latency_ms >= 0


def test_model_digest_is_fetched_once_from_tags_and_cached() -> None:
    tags_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal tags_calls
        if request.url.path == "/api/tags":
            tags_calls += 1
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "qwen3:8b", "digest": "sha256:abc"},
                        {"name": "qwen2.5-coder:7b", "digest": "sha256:def"},
                    ]
                },
            )
        return httpx.Response(200, json=CHAT_REPLY)

    llm = OllamaLLM(Settings(), client=client_with(handler))

    first = llm.complete(request_for())
    second = llm.complete(request_for())

    assert first.model_digest == "sha256:abc"
    assert second.model_digest == "sha256:abc"
    assert tags_calls == 1
    assert llm.describe().digest == "sha256:def"


def test_digest_lookup_failure_does_not_fail_the_completion() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            raise httpx.ConnectError("tags down", request=request)
        return httpx.Response(200, json=CHAT_REPLY)

    response = OllamaLLM(Settings(), client=client_with(handler)).complete(request_for())

    assert response.content == CHAT_REPLY["message"]["content"]
    assert response.model_digest is None
