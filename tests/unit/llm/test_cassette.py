"""Unit tests for cassette record/replay (S22/D18)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sqlagent.adapters.llm.cassette import (
    PREVIEW_CHARS,
    CassetteStore,
    RecordingLLM,
    ReplayLLM,
    prompt_preview,
    request_key,
)
from sqlagent.adapters.llm.scripted import ScriptedLLM
from sqlagent.application.ports import LLMOptions, LLMRequest, LLMResponse
from sqlagent.domain.errors import CassetteMiss, ConfigError
from sqlagent.domain.models import TokenUsage

SCHEMA = {
    "type": "object",
    "properties": {"action": {"type": "string"}},
    "required": ["action"],
}


def make_request(
    *,
    content: str = "How many tenders are in the database?",
    stage: str = "generate",
    schema: dict[str, object] | None = None,
    options: LLMOptions | None = None,
    question_id: str | None = "q001",
) -> LLMRequest:
    return LLMRequest(
        messages=(
            {"role": "system", "content": "Answer in JSON."},
            {"role": "user", "content": content},
        ),
        model="qwen3:8b",
        stage=stage,  # type: ignore[arg-type]
        json_schema=SCHEMA if schema is None else schema,
        options=options or LLMOptions(),
        question_id=question_id,
    )


def test_record_then_replay_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "cassette.jsonl"
    scripted = ScriptedLLM(
        [
            LLMResponse(
                content='{"action": "final_sql", "sql": "SELECT 1"}',
                usage=TokenUsage(prompt=101, completion=17),
                latency_ms=42.5,
                model="qwen3:8b",
                model_digest="sha256:abc",
                backend="scripted",
            )
        ]
    )
    recording = RecordingLLM(scripted, path)
    request = make_request()

    live = recording.complete(request)
    replayed = ReplayLLM(path).complete(request)

    assert live.content == replayed.content
    assert replayed.usage == TokenUsage(prompt=101, completion=17)
    assert replayed.latency_ms == 42.5
    assert replayed.model == "qwen3:8b"
    assert replayed.model_digest == "sha256:abc"
    assert replayed.backend == "replay"
    assert len(CassetteStore(path)) == 1


def test_cassette_miss_mentions_record_flag(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    replay = ReplayLLM(path)

    with pytest.raises(CassetteMiss) as excinfo:
        replay.complete(make_request())

    message = str(excinfo.value)
    assert "--record" in message
    assert "no recorded" in message
    assert Path(path).name in message


def test_cassette_uses_key_of_canonical_request(tmp_path: Path) -> None:
    path = tmp_path / "cassette.jsonl"
    recording = RecordingLLM(ScriptedLLM(["content"]), path)
    request = make_request()

    recording.complete(request)

    raw = path.read_text(encoding="utf-8").strip()
    record = json.loads(raw)
    expected = hashlib.sha256(
        json.dumps(
            {
                "model": "qwen3:8b",
                "stage": "generate",
                "messages": [
                    {"role": "system", "content": "Answer in JSON."},
                    {"role": "user", "content": "How many tenders are in the database?"},
                ],
                "json_schema": SCHEMA,
                "options": {
                    "temperature": 0.0,
                    "seed": 42,
                    "num_ctx": 8192,
                    "num_predict": 768,
                },
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert record["key"] == expected == request_key(request)
    assert record["question_id"] == "q001"


def test_cassette_does_not_store_full_prompt(tmp_path: Path) -> None:
    path = tmp_path / "cassette.jsonl"
    secret = "UNIQUE_SECRET_SENTINEL_" + "x" * 400
    request = make_request(content=secret)
    RecordingLLM(ScriptedLLM(["ok"]), path).complete(request)

    text = path.read_text(encoding="utf-8")
    assert secret not in text
    assert "UNIQUE_SECRET_SENTINEL_" in text  # the preview may keep a short prefix
    record = json.loads(text)
    assert len(record["prompt_preview"]) <= PREVIEW_CHARS
    assert prompt_preview(request) == record["prompt_preview"]


def test_cassette_key_is_stable_and_option_sensitive(tmp_path: Path) -> None:
    request = make_request()

    assert request_key(request) == request_key(make_request())
    assert request_key(request) != request_key(make_request(options=LLMOptions(temperature=0.7)))
    assert request_key(request) != request_key(make_request(stage="repair"))
    assert request_key(request) != request_key(make_request(schema={"type": "string"}))


def test_recording_appends_jsonl_lines(tmp_path: Path) -> None:
    path = tmp_path / "cassette.jsonl"
    recording = RecordingLLM(ScriptedLLM(["one", "two"]), path)

    recording.complete(make_request(stage="generate"))
    recording.complete(make_request(stage="narrate"))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert {json.loads(line)["stage"] for line in lines} == {"generate", "narrate"}


def test_malformed_cassette_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="not valid JSON"):
        ReplayLLM(path)


def test_cassette_missing_required_field_raises_config_error(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.jsonl"
    path.write_text(json.dumps({"key": "abc"}) + "\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="missing"):
        ReplayLLM(path)


def test_describe_reports_cassette_details(tmp_path: Path) -> None:
    path = tmp_path / "cassette.jsonl"
    recording = RecordingLLM(ScriptedLLM(["x"]), path)
    recording.complete(make_request())

    assert recording.describe().backend == "recording"
    replay = ReplayLLM(path).describe()
    assert replay.backend == "replay"
    assert replay.model == "qwen3:8b"
    assert path.name in replay.detail
