"""Deterministic scripted ``LLMPort`` for unit tests and demos (D17).

``ScriptedLLM`` replays a fixed sequence (or calls a function) and records every
request, so agent tests can assert on prompts without any network or model.  A
response may be a string, a pre-built :class:`LLMResponse`, or an exception
instance (raised verbatim), which keeps error paths scriptable as well.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from sqlagent.application.ports import BackendInfo, LLMRequest, LLMResponse
from sqlagent.domain.errors import LLMError
from sqlagent.domain.models import TokenUsage

type ScriptedResult = str | LLMResponse | BaseException
type ScriptedResponder = Callable[[LLMRequest], ScriptedResult]
type ScriptedResponses = Iterable[ScriptedResult] | ScriptedResponder


def _count_tokens(text: str) -> int:
    """Cheap deterministic token estimate (characters); never used for scoring."""

    return max(1, len(text) // 4)


class ScriptedLLM:
    """A scripted backend that records requests and returns canned content."""

    def __init__(
        self,
        responses: ScriptedResponses,
        *,
        model: str = "scripted",
        digest: str = "scripted",
        latency_ms: float = 0.0,
    ) -> None:
        self._responder: ScriptedResponder | None
        self._response_list: list[ScriptedResult] = []
        if callable(responses):
            self._responder = responses
        else:
            self._responder = None
            self._response_list = list(responses)
        self._model = model
        self._digest = digest
        self._latency_ms = latency_ms
        self.calls: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Return the next scripted response; raise when the script is exhausted."""

        self.calls.append(request)
        if self._responder is not None:
            result = self._responder(request)
        else:
            index = len(self.calls) - 1
            if index >= len(self._response_list):
                raise LLMError(
                    f"scripted LLM exhausted after {len(self._response_list)} response(s); "
                    f"received {len(self.calls)} call(s)"
                )
            result = self._response_list[index]
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, LLMResponse):
            return result
        content = str(result)
        return LLMResponse(
            content=content,
            usage=TokenUsage(
                prompt=sum(_count_tokens(str(m.get("content", ""))) for m in request.messages),
                completion=_count_tokens(content),
            ),
            latency_ms=self._latency_ms,
            model=request.model or self._model,
            model_digest=self._digest,
            backend="scripted",
            stage=request.stage,
        )

    def describe(self) -> BackendInfo:
        return BackendInfo(
            backend="scripted",
            model=self._model,
            digest=self._digest,
            detail=f"{len(self._response_list)} scripted response(s)",
        )
