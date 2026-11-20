"""Test-only sabotaged backends used to prove the regression gate bites (D17)."""

from __future__ import annotations

import json
from collections.abc import Mapping

from sqlagent.application.evaluation.benchmark import Benchmark, Expect
from sqlagent.application.ports import BackendInfo, LLMRequest, LLMResponse
from sqlagent.domain.models import TokenUsage
from tests.support.oracle_llm import OracleLLM

WRONG_RESULT_SQL = "SELECT 0 AS n"
WRONG_TABLE_SQL = "SELECT COUNT(*) AS n FROM suppliers"


class SabotagedLLM:
    """Delegate non-answerable items to the oracle but break answerable SQL.

    ``mode="no_repair"`` returns a valid but wrong SQL statement for every
    answerable item (so the eval gate must fail); ``mode="bad_retrieval"``
    returns SQL over the wrong table.
    """

    def __init__(self, benchmark: Benchmark, mode: str = "no_repair") -> None:
        if mode not in {"no_repair", "bad_retrieval"}:
            raise ValueError(f"unknown sabotage mode: {mode!r}")
        self.mode = mode
        self._oracle = OracleLLM(benchmark)

    @staticmethod
    def _response(content: Mapping[str, object]) -> LLMResponse:
        return LLMResponse(
            content=json.dumps(content, ensure_ascii=False),
            usage=TokenUsage(prompt=10, completion=5),
            latency_ms=0.0,
            model="sabotaged",
            model_digest="sabotaged-v1",
            backend="sabotaged",
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        if request.stage == "narrate":
            return self._oracle.complete(request)
        item = self._oracle.find_item(request)
        if item is None or item.expect is not Expect.ANSWER:
            return self._oracle.complete(request)
        sql = WRONG_RESULT_SQL if self.mode == "no_repair" else WRONG_TABLE_SQL
        return self._response(
            {"plan": ["deliberately wrong SQL"], "action": "final_sql", "sql": sql}
        )

    def describe(self) -> BackendInfo:
        return BackendInfo(
            backend=f"sabotaged-{self.mode}",
            model="sabotaged",
            digest="sabotaged-v1",
            available=True,
            detail=self.mode,
        )


__all__ = ["SabotagedLLM"]
