"""The bounded analyst state machine (S9-S14/D5).

One :class:`AnalystAgent` instance is stateless between runs.  ``run`` executes a
handler table keyed by :class:`Phase`; every loop iteration either advances the
phase or terminates, and the hard :data:`MAX_LLM_CALLS` cap in ``_request_action``
guarantees a bounded number of model calls even for adversarial outputs.

The agent never raises: expected failures become a ``failed`` answer with a
friendly message, unexpected ones are logged with an ``error_id`` and mapped to
the same terminal state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any, Final

import structlog

from sqlagent.application.agent.events import (
    AgentEvent,
    EventKind,
    EventSink,
    NullSink,
)
from sqlagent.application.agent.prompts import (
    generate_messages,
    narrate_fallback,
    narrate_messages,
    repair_messages,
)
from sqlagent.application.agent.protocol import (
    GENERATE_SCHEMA,
    NARRATE_SCHEMA,
    GenerateAction,
    parse_action,
    parse_narration,
)
from sqlagent.application.agent.state import (
    MAX_LLM_CALLS,
    MAX_QUESTION_CHARS,
    TERMINAL_PHASES,
    Phase,
    TurnContext,
)
from sqlagent.application.agent.tools import LookupValuesTool
from sqlagent.application.ports import (
    LLMOptions,
    LLMPort,
    LLMRequest,
    LLMResponse,
    LLMStage,
    WarehousePort,
)
from sqlagent.config import Settings
from sqlagent.domain.chart import choose_chart
from sqlagent.domain.errors import GuardrailViolation, LLMError, LLMProtocolError, SqlExecutionError
from sqlagent.domain.language import detect_language
from sqlagent.domain.models import (
    AgentAnswer,
    AttemptKind,
    AttemptRecord,
    ChartSpec,
    Language,
    PhaseTiming,
    QueryResult,
    Status,
    TokenUsage,
    Trace,
)
from sqlagent.domain.retrieval import Bm25Retriever, FewShot, RetrievalResult
from sqlagent.domain.sanitize import DataSanitizer
from sqlagent.domain.semantic import SemanticLayer
from sqlagent.domain.sql_policy import WRITE_INTENT_CODES, SqlPolicy, ValidatedQuery

logger = structlog.get_logger(__name__)

EXECUTION_ERROR_CODE: Final = "EXECUTION_ERROR"
UNEXPECTED_ERROR_CODE: Final = "UNEXPECTED_ERROR"


class _BudgetExceeded(Exception):
    """The hard LLM-call cap was reached before the run could finish."""


class _ProtocolFailure(Exception):
    """The model failed the action protocol twice in a row."""


@dataclass
class _RunState:
    """Mutable per-run state; never shared between runs or threads."""

    question: str
    language: Language
    language_override: Language | None = None
    phase: Phase = Phase.UNDERSTAND
    history: TurnContext | None = None
    retrieval: RetrievalResult | None = None
    action: GenerateAction | None = None
    sql: str | None = None
    validated: ValidatedQuery | None = None
    result: QueryResult | None = None
    chart: ChartSpec | None = None
    text: str = ""
    status: Status | None = None
    attempts: list[AttemptRecord] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)
    guardrail_events: list[str] = field(default_factory=list)
    injection_flags: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    llm_calls: int = 0
    tool_calls: int = 0
    repairs: int = 0
    pending_kind: AttemptKind = "generate"
    last_error: str = ""
    timings: list[PhaseTiming] = field(default_factory=list)


class AnalystAgent:
    """Explicit, bounded state machine turning a question into an ``AgentAnswer``."""

    def __init__(  # noqa: PLR0913, PLR0917 - explicit dependency injection
        self,
        llm: LLMPort,
        warehouse: WarehousePort,
        policy: SqlPolicy,
        retriever: Bm25Retriever,
        semantic: SemanticLayer,
        settings: Settings,
        *,
        sink: EventSink | None = None,
        sanitizer: DataSanitizer | None = None,
        narrate: bool = True,
        retrieve: bool = True,
        fewshots: tuple[FewShot, ...] = (),
    ) -> None:
        self._llm = llm
        self._warehouse = warehouse
        self._policy = policy
        self._retriever = retriever
        self._semantic = semantic
        self._settings = settings
        self._sink = sink or NullSink()
        self._sanitizer = sanitizer or DataSanitizer()
        self._narrate = narrate
        self._retrieval_enabled = retrieve
        self._fewshots = tuple(fewshots)
        self._lookup = LookupValuesTool(warehouse, semantic, sanitizer=self._sanitizer)
        self._handlers = {
            Phase.UNDERSTAND: self._understand,
            Phase.RETRIEVE: self._retrieve,
            Phase.GENERATE: self._generate,
            Phase.TOOL: self._tool,
            Phase.VALIDATE: self._validate,
            Phase.EXECUTE: self._execute,
            Phase.REPAIR: self._repair,
            Phase.CHART: self._chart,
            Phase.NARRATE: self._narrate_phase,
        }

    # -- public API ----------------------------------------------------
    def run(
        self,
        question: str,
        *,
        language: Language | None = None,
        history: TurnContext | None = None,
    ) -> AgentAnswer:
        """Answer one question; never raises, always returns a valid answer."""

        state = _RunState(
            question=question,
            language=language or Language.EN,
            language_override=language,
            history=history,
        )
        try:
            while state.phase not in TERMINAL_PHASES:
                handler = self._handlers.get(state.phase)
                if handler is None:  # pragma: no cover - table covers every non-terminal phase
                    raise RuntimeError(f"no handler for phase {state.phase}")
                started = perf_counter()
                next_phase = handler(state)
                elapsed_ms = (perf_counter() - started) * 1000
                state.timings.append(PhaseTiming(phase=state.phase.value, elapsed_ms=elapsed_ms))
                state.phase = next_phase
        except _BudgetExceeded:
            state.status = Status.FAILED
            state.text = self._failure_text(state.language)
            state.phase = Phase.FAILED
        except _ProtocolFailure:
            state.status = Status.FAILED
            state.text = self._failure_text(state.language)
            state.phase = Phase.FAILED
        except LLMError as exc:
            self._log_failure(state, exc, "llm")
            state.status = Status.FAILED
            state.text = self._failure_text(state.language)
            state.phase = Phase.FAILED
        except Exception as exc:
            self._log_failure(state, exc, "unexpected")
            state.status = Status.FAILED
            state.text = self._failure_text(state.language)
            state.phase = Phase.FAILED
        return self._answer(state)

    # -- handlers ------------------------------------------------------
    def _understand(self, state: _RunState) -> Phase:
        self._emit(state, EventKind.PHASE, Phase.UNDERSTAND)
        text = state.question.strip()
        state.language = state.language_override or detect_language(text)
        if not text or len(text) > MAX_QUESTION_CHARS:
            state.status = Status.CLARIFICATION
            state.text = (
                "Por favor formula una pregunta concreta de hasta 600 caracteres."
                if state.language is Language.ES
                else "Please ask one concrete question of up to 600 characters."
            )
            self._emit(state, EventKind.ANSWER, None, {"status": state.status.value})
            return Phase.CLARIFY
        return Phase.RETRIEVE

    def _retrieve(self, state: _RunState) -> Phase:
        self._emit(state, EventKind.PHASE, Phase.RETRIEVE)
        if self._retrieval_enabled:
            state.retrieval = self._retriever.search(state.question)
        else:
            # D13 `--no-retrieval` ablation: send every table and metric.
            state.retrieval = RetrievalResult(
                tables=tuple(table.name for table in self._semantic.tables),
                metrics=self._semantic.metrics,
                fewshots=(),
                docs=(),
            )
        self._emit(
            state,
            EventKind.RETRIEVAL,
            None,
            {"tables": list(state.retrieval.tables)},
        )
        return Phase.GENERATE

    def _generate(self, state: _RunState) -> Phase:
        self._emit(state, EventKind.PHASE, Phase.GENERATE)
        assert state.retrieval is not None  # noqa: S101 - RETRIEVE always precedes GENERATE
        messages = generate_messages(
            state.question,
            state.language,
            state.retrieval,
            self._semantic,
            history=state.history,
            tool_results=tuple(state.tool_results),
            fewshots=self._fewshots,
        )
        state.action = self._request_action(state, messages, stage="generate")
        action = state.action
        if action.action == "final_sql":
            state.pending_kind = "generate"
            state.sql = action.sql
            return Phase.VALIDATE
        if action.action == "lookup_values":
            return Phase.TOOL
        if action.action == "clarify":
            state.status = Status.CLARIFICATION
            state.text = action.message or self._failure_text(state.language)
            self._emit(state, EventKind.ANSWER, None, {"status": state.status.value})
            return Phase.CLARIFY
        state.status = Status.REFUSED
        state.text = action.message or self._refusal_text(state.language)
        self._emit(state, EventKind.ANSWER, None, {"status": state.status.value})
        return Phase.REFUSE

    def _tool(self, state: _RunState) -> Phase:
        self._emit(state, EventKind.PHASE, Phase.TOOL)
        if state.tool_calls >= self._settings.max_tool_calls:
            state.status = Status.FAILED
            state.text = self._failure_text(state.language)
            return Phase.FAILED
        action = state.action
        assert action is not None  # noqa: S101
        assert action.lookup is not None  # noqa: S101
        result = self._lookup.run(action.lookup.column, action.lookup.query)
        state.tool_calls += 1
        state.injection_flags += result.flags
        if result.ok:
            state.tool_results.append(result.block)
            self._emit(
                state,
                EventKind.ATTEMPT,
                None,
                {"tool": "lookup_values", "values": list(result.values)},
            )
        else:
            state.tool_results.append(f"lookup_values error: {result.error}")
        state.action = None
        return Phase.GENERATE

    def _validate(self, state: _RunState) -> Phase:
        self._emit(state, EventKind.PHASE, Phase.VALIDATE)
        sql = state.sql or ""
        try:
            validated = self._policy.validate(sql)
        except GuardrailViolation as exc:
            state.attempts.append(
                AttemptRecord(
                    kind=state.pending_kind,
                    sql=sql,
                    error_code=exc.code.value,
                    error_message=exc.message,
                )
            )
            state.guardrail_events.append(exc.code.value)
            self._emit(
                state,
                EventKind.ATTEMPT,
                None,
                {"error_code": exc.code.value, "kind": state.pending_kind},
            )
            if exc.code in WRITE_INTENT_CODES:
                state.status = Status.REFUSED
                state.text = self._refusal_text(state.language)
                return Phase.REFUSE
            state.last_error = str(exc)
            if state.repairs >= self._settings.max_repairs:
                state.status = Status.FAILED
                state.text = self._failure_text(state.language)
                return Phase.FAILED
            return Phase.REPAIR
        state.attempts.append(AttemptRecord(kind=state.pending_kind, sql=sql))
        state.validated = validated
        state.sql = validated.sql
        self._emit(state, EventKind.SQL, None, {"sql": state.sql})
        return Phase.EXECUTE

    def _execute(self, state: _RunState) -> Phase:
        self._emit(state, EventKind.PHASE, Phase.EXECUTE)
        assert state.validated is not None  # noqa: S101 - VALIDATE precedes EXECUTE
        try:
            result = self._warehouse.execute(state.validated)
        except SqlExecutionError as exc:
            self._record_execution_error(state, str(exc))
            state.last_error = str(exc)
            if state.repairs >= self._settings.max_repairs:
                state.status = Status.FAILED
                state.text = self._failure_text(state.language)
                return Phase.FAILED
            return Phase.REPAIR
        state.result = result
        self._emit(
            state,
            EventKind.RESULT,
            None,
            {"row_count": result.row_count, "truncated": result.truncated},
        )
        return Phase.CHART

    def _repair(self, state: _RunState) -> Phase:
        self._emit(state, EventKind.PHASE, Phase.REPAIR)
        if state.repairs >= self._settings.max_repairs:
            state.status = Status.FAILED
            state.text = self._failure_text(state.language)
            return Phase.FAILED
        assert state.retrieval is not None  # noqa: S101
        state.repairs += 1
        messages = repair_messages(
            state.question,
            state.language,
            state.retrieval,
            self._semantic,
            previous_sql=state.sql or "",
            error=state.last_error,
            history=state.history,
            tool_results=tuple(state.tool_results),
            fewshots=self._fewshots,
        )
        action = self._request_action(state, messages, stage="repair")
        state.action = action
        if action.action == "final_sql":
            state.pending_kind = "repair"
            state.sql = action.sql
            return Phase.VALIDATE
        if action.action == "clarify":
            state.status = Status.CLARIFICATION
            state.text = action.message or self._failure_text(state.language)
            return Phase.CLARIFY
        if action.action == "refuse":
            state.status = Status.REFUSED
            state.text = action.message or self._refusal_text(state.language)
            return Phase.REFUSE
        state.status = Status.FAILED
        state.text = self._failure_text(state.language)
        return Phase.FAILED

    def _chart(self, state: _RunState) -> Phase:
        self._emit(state, EventKind.PHASE, Phase.CHART)
        assert state.result is not None  # noqa: S101
        state.chart = choose_chart(state.result.columns, state.result.rows, "query_result")
        self._emit(state, EventKind.CHART, None, {"kind": getattr(state.chart, "kind", "none")})
        return Phase.NARRATE

    def _narrate_phase(self, state: _RunState) -> Phase:
        self._emit(state, EventKind.PHASE, Phase.NARRATE)
        assert state.result is not None  # noqa: S101
        block = self._sanitizer.render_block_result(state.result.rows, "rows")
        state.injection_flags += block.flags
        if not self._narrate or state.llm_calls >= MAX_LLM_CALLS:
            state.text = narrate_fallback(state.language, state.result)
        else:
            messages = narrate_messages(
                state.question,
                state.language,
                state.result,
                sanitizer=self._sanitizer,
            )
            try:
                response = self._complete(state, messages, stage="narrate", schema=NARRATE_SCHEMA)
                state.text = parse_narration(response.content).answer
            except (LLMError, LLMProtocolError):
                state.text = narrate_fallback(state.language, state.result)
        self._emit(state, EventKind.ANSWER, None, {"status": Status.OK.value})
        return Phase.DONE

    # -- LLM calls -----------------------------------------------------
    def _request_action(
        self,
        state: _RunState,
        messages: tuple[dict[str, str], ...],
        *,
        stage: LLMStage,
    ) -> GenerateAction:
        conversation = list(messages)
        retried = False
        while True:
            if state.llm_calls >= MAX_LLM_CALLS:
                raise _BudgetExceeded
            response = self._complete(
                state,
                tuple(conversation),
                stage=stage,
                schema=GENERATE_SCHEMA,
            )
            try:
                return parse_action(response.content)
            except LLMProtocolError as exc:
                if retried:
                    raise _ProtocolFailure(str(exc)) from exc
                retried = True
                conversation.append({"role": "assistant", "content": response.content})
                conversation.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response was invalid ({exc}). Return exactly one "
                            "JSON object matching the schema, with no markdown fences and no "
                            "extra fields."
                        ),
                    }
                )

    def _complete(
        self,
        state: _RunState,
        messages: tuple[dict[str, str], ...],
        *,
        stage: LLMStage,
        schema: dict[str, Any],
    ) -> LLMResponse:
        if state.llm_calls >= MAX_LLM_CALLS:
            raise _BudgetExceeded
        options = LLMOptions(
            temperature=self._settings.temperature,
            seed=self._settings.seed,
            num_ctx=self._settings.num_ctx,
            num_predict=self._settings.num_predict,
        )
        response = self._llm.complete(
            LLMRequest(
                messages=messages,
                model=self._settings.model,
                stage=stage,
                json_schema=schema,
                options=options,
            )
        )
        state.llm_calls += 1
        state.usage += response.usage
        return response

    # -- terminal helpers ---------------------------------------------
    def _answer(self, state: _RunState) -> AgentAnswer:
        status = state.status or Status.OK
        trace = Trace(
            phases=tuple(state.timings),
            attempts=tuple(state.attempts),
            retrieved_tables=state.retrieval.tables if state.retrieval else (),
            tool_calls=state.tool_calls,
            guardrail_events=tuple(state.guardrail_events),
            injection_flags=state.injection_flags,
            usage=state.usage,
            llm_calls=state.llm_calls,
        )
        if status is Status.OK:
            self._emit(state, EventKind.DONE, None, {"status": status.value})
            return AgentAnswer(
                status=status,
                language=state.language,
                text=state.text,
                sql=state.sql,
                result=state.result,
                chart=state.chart,
                trace=trace,
            )
        return AgentAnswer(
            status=status,
            language=state.language,
            text=state.text,
            trace=trace,
        )

    def _record_execution_error(self, state: _RunState, message: str) -> None:
        if state.attempts:
            state.attempts[-1] = replace(
                state.attempts[-1],
                error_code=EXECUTION_ERROR_CODE,
                error_message=message[:300],
            )
        self._emit(
            state,
            EventKind.ATTEMPT,
            None,
            {"error_code": EXECUTION_ERROR_CODE, "kind": state.pending_kind},
        )

    def _log_failure(self, state: _RunState, exc: BaseException, category: str) -> None:
        error_id = uuid.uuid4().hex[:12]
        logger.error(
            "agent.failed",
            error_id=error_id,
            category=category,
            error_type=type(exc).__name__,
            detail=str(exc)[:300],
        )
        self._emit(state, EventKind.ERROR, None, {"error_id": error_id, "category": category})

    def _emit(
        self,
        state: _RunState,
        kind: EventKind,
        phase: Phase | None,
        payload: dict[str, object] | None = None,
    ) -> None:
        try:
            self._sink.emit(AgentEvent(kind=kind, phase=phase, payload=payload or {}))
        except Exception:
            logger.warning("agent.sink_failed", kind=kind.value)

    @staticmethod
    def _failure_text(language: Language) -> str:
        if language is Language.ES:
            return (
                "No pude completar la consulta con los datos disponibles. "
                "Intenta reformular la pregunta."
            )
        return (
            "I could not complete the query with the available data. Try rephrasing the question."
        )

    @staticmethod
    def _refusal_text(language: Language) -> str:
        if language is Language.ES:
            return (
                "No puedo ejecutar esa operación: este analista solo realiza consultas de "
                "lectura (SELECT) sobre el almacén de datos."
            )
        return (
            "I cannot run that operation: this analyst only performs read-only SELECT "
            "queries against the data warehouse."
        )


__all__ = ["EXECUTION_ERROR_CODE", "UNEXPECTED_ERROR_CODE", "AnalystAgent"]
