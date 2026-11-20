"""Test-only ``OracleLLM``: answers GENERATE with the benchmark gold SQL (D17).

The oracle proves the evaluation harness scores a perfect run.  It matches the
benchmark item by the ``QUESTION (<lang>): ...`` line that the prompt builders
always emit, so it does not need a production test hook.  Non-answerable items
produce the action their ``expect`` requires.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from sqlagent.application.evaluation.benchmark import Benchmark, BenchmarkItem, Expect
from sqlagent.application.ports import BackendInfo, LLMRequest, LLMResponse
from sqlagent.domain.models import TokenUsage

_QUESTION_RE = re.compile(r"^QUESTION \((?:es|en)\): (.+)$", re.MULTILINE)


def _user_text(request: LLMRequest) -> str:
    for message in reversed(request.messages):
        if str(message.get("role", "")) == "user":
            return str(message.get("content", ""))
    return ""


class OracleLLM:
    """Deterministic backend returning the benchmark gold SQL for each question."""

    def __init__(self, benchmark: Benchmark) -> None:
        self.benchmark = benchmark
        self._by_question = {item.question: item for item in benchmark.items}
        self.requests: list[LLMRequest] = []

    def find_item(self, request: LLMRequest) -> BenchmarkItem | None:
        """Return the benchmark item whose question is embedded in the prompt."""

        match = _QUESTION_RE.search(_user_text(request))
        if match is None:
            return None
        return self._by_question.get(match.group(1).strip())

    @staticmethod
    def _response(content: Mapping[str, object] | str) -> LLMResponse:
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        return LLMResponse(
            content=text,
            usage=TokenUsage(prompt=10, completion=5),
            latency_ms=0.0,
            model="oracle",
            model_digest="oracle-v1",
            backend="oracle",
        )

    def _action_for(self, item: BenchmarkItem) -> LLMResponse:
        if item.expect is Expect.ANSWER and item.gold_sql is not None:
            return self._response(
                {
                    "plan": ["read schema", "write gold SQL"],
                    "action": "final_sql",
                    "sql": item.gold_sql,
                }
            )
        if item.expect is Expect.REFUSAL:
            return self._response(
                {
                    "plan": ["refuse unsafe request"],
                    "action": "refuse",
                    "message": "This request is out of scope for the read-only analyst.",
                }
            )
        return self._response(
            {
                "plan": ["ask for clarification"],
                "action": "clarify",
                "message": "Could you clarify which entity or metric you mean?",
            }
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if request.stage == "narrate":
            return self._response({"answer": "The query returned the requested result."})
        item = self.find_item(request)
        if item is None:  # pragma: no cover - only used with benchmark prompts
            return self._response(
                {"plan": ["refuse"], "action": "refuse", "message": "Unknown question."}
            )
        return self._action_for(item)

    def describe(self) -> BackendInfo:
        return BackendInfo(
            backend="oracle",
            model="oracle",
            digest="oracle-v1",
            available=True,
            detail="test oracle",
        )


__all__ = ["OracleLLM"]
