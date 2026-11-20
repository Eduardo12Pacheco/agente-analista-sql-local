"""Ollama ``LLMPort`` adapter with schema-constrained outputs (D12/S21).

The HTTP client is injectable so contract tests can use ``httpx.MockTransport``
without opening a socket.  Connection failures retry twice with backoff; every
failure is mapped to an actionable ``LLMError`` that names the exact pull/start
command the user needs.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from sqlagent.application.ports import (
    BackendInfo,
    LLMRequest,
    LLMResponse,
)
from sqlagent.config import Settings
from sqlagent.domain.errors import ConfigError, LLMError
from sqlagent.domain.models import TokenUsage

logger = structlog.get_logger(__name__)

BACKOFF_SECONDS: tuple[float, ...] = (0.5, 1.5)
MAX_ATTEMPTS = 3
HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_BAD_REQUEST = 400
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DOCKER_HINT = (
    "start Ollama with Docker: scripts/ollama-docker.sh up && scripts/ollama-docker.sh pull {model}"
)


@dataclass(frozen=True, slots=True)
class OllamaProbe:
    """Result of the two doctor probes (``/api/version`` and ``/api/tags``)."""

    reachable: bool
    version: str | None = None
    models: tuple[str, ...] = ()
    model_present: bool = False
    detail: str = ""


def is_loopback_url(url: str) -> bool:
    """Return whether ``url`` points at the local machine (S19)."""

    try:
        host = httpx.URL(url).host
    except (httpx.InvalidURL, ValueError):
        return False
    return host in LOOPBACK_HOSTS


class OllamaLLM:
    """A synchronous Ollama chat backend with JSON-schema ``format``."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.url = str(settings.ollama_url).rstrip("/")
        self._sleep = sleep
        self._digests: dict[str, str] = {}
        if not is_loopback_url(self.url):
            if not settings.allow_remote_llm:
                raise ConfigError(
                    f"Ollama URL {self.url!r} is not loopback; only the configured "
                    "Ollama endpoint may receive data (S19). Set "
                    "SQLAGENT_ALLOW_REMOTE_LLM=1 to allow a remote backend."
                )
            logger.warning("llm.remote_url", url=self.url)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(settings.request_timeout_s, connect=3.0)
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OllamaLLM:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- LLMPort -------------------------------------------------------
    def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self._payload(request)
        last_error: str = "unknown error"
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.post(f"{self.url}/api/chat", json=payload)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < MAX_ATTEMPTS - 1:
                    self._sleep(BACKOFF_SECONDS[attempt])
                continue
            if response.status_code == HTTP_NOT_FOUND:
                raise LLMError(self._missing_model_message(request.model, response))
            if response.status_code >= HTTP_BAD_REQUEST:
                raise LLMError(
                    f"Ollama returned HTTP {response.status_code}: "
                    f"{response.text[:300]}. {DOCKER_HINT.format(model=request.model)}"
                )
            return self._parse(response, request)
        raise LLMError(
            f"Ollama is not reachable at {self.url} after {MAX_ATTEMPTS} attempts "
            f"({last_error}). {DOCKER_HINT.format(model=request.model)}"
        )

    def describe(self) -> BackendInfo:
        return BackendInfo(
            backend="ollama",
            model=self.settings.model,
            digest=self._digests.get(self.settings.model),
            detail=self.url,
        )

    # -- doctor --------------------------------------------------------
    def probe(self) -> OllamaProbe:
        """Check reachability, installed models and model presence (S21/S39)."""

        try:
            version_response = self._client.get(
                f"{self.url}/api/version", timeout=httpx.Timeout(3.0)
            )
            version_response.raise_for_status()
            version_payload = version_response.json()
            version = str(version_payload.get("version", "")) or None
        except (httpx.HTTPError, ValueError) as exc:
            return OllamaProbe(reachable=False, detail=f"{type(exc).__name__}: {exc}")
        try:
            tags_response = self._client.get(f"{self.url}/api/tags", timeout=httpx.Timeout(3.0))
            tags_response.raise_for_status()
            tags_payload = tags_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return OllamaProbe(
                reachable=True,
                version=version,
                detail=f"cannot list models: {type(exc).__name__}: {exc}",
            )
        models: list[str] = []
        for entry in tags_payload.get("models", []):
            if isinstance(entry, dict) and entry.get("name"):
                name = str(entry["name"])
                models.append(name)
                digest = entry.get("digest")
                if digest:
                    self._digests[name] = str(digest)
        wanted = self.settings.model
        present = any(name == wanted or name.startswith(f"{wanted}:") for name in models)
        return OllamaProbe(
            reachable=True,
            version=version,
            models=tuple(models),
            model_present=present,
        )

    # -- internals -----------------------------------------------------
    def _payload(self, request: LLMRequest) -> dict[str, Any]:
        options = request.options
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {
                    "role": str(message.get("role", "user")),
                    "content": str(message.get("content", "")),
                }
                for message in request.messages
            ],
            "stream": False,
            "keep_alive": "30m",
            "options": {
                "temperature": options.temperature,
                "seed": options.seed,
                "num_ctx": options.num_ctx,
                "num_predict": options.num_predict,
            },
        }
        if request.json_schema is not None:
            payload["format"] = request.json_schema
        if request.model.startswith("qwen3"):
            payload["think"] = False
        return payload

    def _parse(self, response: httpx.Response, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("Ollama returned a non-JSON response") from exc
        if not isinstance(data, dict):
            raise LLMError("Ollama returned a JSON value that is not an object")
        message = data.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise LLMError("Ollama response has no string message.content")
        total_duration = data.get("total_duration")
        if isinstance(total_duration, int | float) and total_duration > 0:
            latency_ms = float(total_duration) / 1_000_000.0
        else:  # pragma: no cover - Ollama always reports total_duration
            latency_ms = (time.perf_counter() - started) * 1000.0
        model = str(data.get("model") or request.model)
        return LLMResponse(
            content=message["content"],
            usage=TokenUsage(
                prompt=int(data.get("prompt_eval_count") or 0),
                completion=int(data.get("eval_count") or 0),
            ),
            latency_ms=latency_ms,
            model=model,
            model_digest=self._ensure_digest(model),
            backend="ollama",
            stage=request.stage,
        )

    def _ensure_digest(self, model: str) -> str | None:
        """Fetch the model digest from ``/api/tags`` once (D12); never fail a call."""

        if model in self._digests:
            return self._digests[model]
        try:
            response = self._client.get(f"{self.url}/api/tags", timeout=httpx.Timeout(3.0))
            if response.status_code != HTTP_OK:
                return None
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        for entry in payload.get("models", []):
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            name = str(entry["name"])
            digest = entry.get("digest")
            if digest:
                self._digests[name] = str(digest)
        return self._digests.get(model)

    def _missing_model_message(self, model: str, response: httpx.Response) -> str:
        detail = response.text[:200]
        return (
            f"model {model!r} is not available in Ollama ({detail}). "
            f"Pull it with 'ollama pull {model}' or "
            f"'scripts/ollama-docker.sh pull {model}'."
        )
