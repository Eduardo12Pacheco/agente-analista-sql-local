"""JSONL cassette record/replay for deterministic LLM regression tests (D18).

Records are keyed by the SHA-256 of a canonical request and never contain the
full prompt: only a digest and a short preview are persisted, so cassettes can be
committed safely.  ``RecordingLLM`` decorates any ``LLMPort``; ``ReplayLLM``
returns the recorded content, usage and latency or raises ``CassetteMiss`` with a
re-record hint (CLI exit 4).
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlagent.application.ports import (
    BackendInfo,
    LLMOptions,
    LLMPort,
    LLMRequest,
    LLMResponse,
)
from sqlagent.domain.errors import CassetteMiss, ConfigError
from sqlagent.domain.models import TokenUsage

PREVIEW_CHARS = 200


def _options_payload(options: LLMOptions) -> dict[str, Any]:
    return {
        "temperature": options.temperature,
        "seed": options.seed,
        "num_ctx": options.num_ctx,
        "num_predict": options.num_predict,
    }


def canonical_request(request: LLMRequest) -> dict[str, Any]:
    """Return the request subset that defines cassette identity (D18)."""

    return {
        "model": request.model,
        "stage": request.stage,
        "messages": [
            {"role": str(message.get("role", "")), "content": str(message.get("content", ""))}
            for message in request.messages
        ],
        "json_schema": request.json_schema,
        "options": _options_payload(request.options),
    }


def request_key(request: LLMRequest) -> str:
    """Return the deterministic SHA-256 key for one request."""

    canonical = json.dumps(
        canonical_request(request),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prompt_preview(request: LLMRequest) -> str:
    """Return a prompt prefix suitable for committing (never the full prompt)."""

    text = "\n".join(
        f"{message.get('role', '')}: {message.get('content', '')}" for message in request.messages
    )
    return text[:PREVIEW_CHARS]


@dataclass(frozen=True, slots=True)
class CassetteRecord:
    """One committed JSONL line (D18)."""

    key: str
    stage: str
    question_id: str | None
    prompt_preview: str
    response: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    model: str
    model_digest: str | None
    recorded_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "stage": self.stage,
            "question_id": self.question_id,
            "prompt_preview": self.prompt_preview,
            "response": self.response,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "model_digest": self.model_digest,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_json(cls, data: Any, source: Path, line: int) -> CassetteRecord:
        if not isinstance(data, dict):
            raise ConfigError(f"cassette {source.name}: line {line} must be a JSON object")
        required = (
            "key",
            "stage",
            "prompt_preview",
            "response",
            "prompt_tokens",
            "completion_tokens",
            "latency_ms",
            "model",
            "recorded_at",
        )
        for field in required:
            if field not in data:
                raise ConfigError(f"cassette {source.name}: line {line} is missing {field!r}")
        try:
            return cls(
                key=str(data["key"]),
                stage=str(data["stage"]),
                question_id=None if data.get("question_id") is None else str(data["question_id"]),
                prompt_preview=str(data["prompt_preview"]),
                response=str(data["response"]),
                prompt_tokens=int(data["prompt_tokens"]),
                completion_tokens=int(data["completion_tokens"]),
                latency_ms=float(data["latency_ms"]),
                model=str(data["model"]),
                model_digest=(
                    None if data.get("model_digest") is None else str(data["model_digest"])
                ),
                recorded_at=str(data["recorded_at"]),
            )
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"cassette {source.name}: line {line} has an invalid value: {exc}"
            ) from exc


class CassetteStore:
    """Append-only JSONL store keyed by request digest."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._records = self._read()

    def _read(self) -> dict[str, CassetteRecord]:
        if not self.path.is_file():
            return {}
        records: dict[str, CassetteRecord] = {}
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ConfigError(
                    f"cassette {self.path.name}: line {line_number} is not valid JSON"
                ) from exc
            record = CassetteRecord.from_json(payload, self.path, line_number)
            records[record.key] = record
        return records

    def __len__(self) -> int:
        return len(self._records)

    def get(self, key: str) -> CassetteRecord | None:
        with self._lock:
            return self._records.get(key)

    def first_model(self) -> str:
        """Return the first recorded model name (``""`` for an empty cassette)."""

        with self._lock:
            for record in self._records.values():
                return record.model
        return ""

    def append(
        self,
        request: LLMRequest,
        response: LLMResponse,
        *,
        recorded_at: str | None = None,
    ) -> CassetteRecord:
        """Append one record; repeated keys are overwritten on read (last wins)."""

        record = CassetteRecord(
            key=request_key(request),
            stage=request.stage,
            question_id=request.question_id,
            prompt_preview=prompt_preview(request),
            response=response.content,
            prompt_tokens=response.usage.prompt,
            completion_tokens=response.usage.completion,
            latency_ms=response.latency_ms,
            model=response.model or request.model,
            model_digest=response.model_digest,
            recorded_at=recorded_at or datetime.now(tz=UTC).isoformat(timespec="seconds"),
        )
        line = json.dumps(record.to_json(), ensure_ascii=False)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
            self._records[record.key] = record
        return record


class RecordingLLM:
    """Decorator that records every successful completion to a cassette."""

    def __init__(self, inner: LLMPort, cassette_path: Path) -> None:
        self.inner = inner
        self.store = CassetteStore(Path(cassette_path))

    def complete(self, request: LLMRequest) -> LLMResponse:
        response = self.inner.complete(request)
        self.store.append(request, response)
        return response

    def describe(self) -> BackendInfo:
        info = self.inner.describe()
        detail = f"recording {info.backend}"
        if info.detail:
            detail = f"{detail}: {info.detail}"
        return replace(info, backend="recording", detail=detail)


class ReplayLLM:
    """Replay recorded content, usage and latency; never calls a model."""

    def __init__(self, cassette_path: Path) -> None:
        self.path = Path(cassette_path)
        self.store = CassetteStore(self.path)

    def complete(self, request: LLMRequest) -> LLMResponse:
        key = request_key(request)
        record = self.store.get(key)
        if record is None:
            raise CassetteMiss(
                f"no recorded {request.stage} response for key {key[:12]}… in "
                f"{self.path.name}; re-record the cassette with --record "
                "(for example: sqlagent eval --llm ollama --record)"
            )
        return LLMResponse(
            content=record.response,
            usage=TokenUsage(
                prompt=record.prompt_tokens,
                completion=record.completion_tokens,
            ),
            latency_ms=record.latency_ms,
            model=record.model,
            model_digest=record.model_digest,
            backend="replay",
            stage=record.stage,
        )

    def describe(self) -> BackendInfo:
        return BackendInfo(
            backend="replay",
            model=self.store.first_model(),
            digest=None,
            detail=f"cassette {self.path.name} ({len(self.store)} record(s))",
        )
