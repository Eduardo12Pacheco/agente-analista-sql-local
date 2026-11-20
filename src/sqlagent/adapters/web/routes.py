"""HTTP routes for the local chat (D24).

Rendering is intentionally split between the full answer card (no-JS fallback and
``POST /api/ask``) and small SSE fragments (phase, SQL, result, chart, answer and
error) so the browser swaps only the region that changed.
"""

from __future__ import annotations

import csv
import io
import json
import threading
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from sqlagent import __version__
from sqlagent.adapters.cli.render import answer_to_dict
from sqlagent.adapters.web.i18n import (
    example_questions,
    normalize_language,
    phase_label,
    translate,
)
from sqlagent.adapters.web.sse import ThreadEventSink, format_sse
from sqlagent.adapters.web.templating import render_template, templates
from sqlagent.application.agent.events import AgentEvent
from sqlagent.domain.models import AgentAnswer, Language, Status
from sqlagent.domain.semantic import SemanticTable

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from sqlagent.adapters.web.app import WebState

logger = structlog.get_logger(__name__)

router = APIRouter()

PHASE_ORDER: tuple[str, ...] = (
    "UNDERSTAND",
    "RETRIEVE",
    "GENERATE",
    "VALIDATE",
    "EXECUTE",
    "CHART",
    "NARRATE",
)
_PHASE_ALIASES = {"TOOL": "GENERATE", "REPAIR": "VALIDATE", "DONE": "NARRATE"}
MAX_UI_ROWS = 200


def _state(request: Request) -> WebState:
    return request.app.state.web  # type: ignore[no-any-return]


def _ui_language(request: Request) -> str:
    requested = request.query_params.get("lang")
    if requested:
        return normalize_language(requested)
    settings = _state(request).settings
    if settings.ui_lang != "auto":
        return normalize_language(settings.ui_lang)
    header = request.headers.get("accept-language", "")
    for candidate in header.split(","):
        code = candidate.split(";", 1)[0].strip()
        if code.lower().startswith(("es", "en")):
            return normalize_language(code)
    return "es"


def _ollama_ok(state: WebState) -> bool:
    if state.settings.llm_backend != "ollama":
        return True
    probe = getattr(state.llm, "probe", None)
    if not callable(probe):
        return True
    try:
        return bool(probe().reachable)
    except Exception:  # health must never raise
        return False


def _context(request: Request, language: str, **extra: object) -> dict[str, object]:
    state = _state(request)
    context: dict[str, object] = {
        "request": request,
        "language": language,
        "t": lambda key, **values: translate(language, key, **values),
        "examples": example_questions(language),
        "state": state,
        "demo": state.demo,
        "backend": state.backend,
        "model": state.model,
        "version": state.version,
        "limit": state.settings.max_rows,
        "ui_rows": state.settings.ui_rows,
    }
    context.update(extra)
    return context


def _fragment_context(record_ui_language: str, **extra: object) -> dict[str, object]:
    language = normalize_language(record_ui_language)
    context: dict[str, object] = {
        "language": language,
        "t": lambda key, **values: translate(language, key, **values),
        "limit": 1_000,
        "ui_rows": MAX_UI_ROWS,
    }
    context.update(extra)
    return context


def _steps(current: str, language: str) -> list[dict[str, str]]:
    mapped = _PHASE_ALIASES.get(current.upper(), current.upper())
    active_index = PHASE_ORDER.index(mapped) if mapped in PHASE_ORDER else 0
    steps: list[dict[str, str]] = []
    for index, phase in enumerate(PHASE_ORDER):
        state = "done" if index < active_index else "active" if index == active_index else "pending"
        steps.append({"phase": phase, "label": phase_label(language, phase), "state": state})
    return steps


def _initial_steps(language: str) -> list[dict[str, str]]:
    return _steps("UNDERSTAND", language)


# -- pages -------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    language = _ui_language(request)
    return templates.TemplateResponse(
        request,
        "index.html",
        _context(request, language, initial_answer=None, answer_id=None),
    )


@router.get("/health", response_class=JSONResponse)
async def health(request: Request) -> JSONResponse:
    state = _state(request)
    info = state.warehouse.info()
    payload = {
        "version": __version__,
        "backend": state.backend,
        "model": state.model,
        "ollama_ok": _ollama_ok(state),
        "demo": state.demo,
        "warehouse": {
            "file": info.path.name,
            "manifest_sha256": info.manifest_sha256,
            "tables": dict(info.tables),
            "license": info.license,
            "source_url": info.source_url,
        },
    }
    return JSONResponse(payload)


@router.get("/schema", response_class=HTMLResponse)
async def schema(request: Request) -> HTMLResponse:
    state = _state(request)
    language = _ui_language(request)
    catalog = state.warehouse.catalog()
    tables: list[dict[str, object]] = []
    for name in sorted(catalog.tables):
        semantic_table: SemanticTable | None = state.semantic.table(name)
        columns = []
        for column in catalog.tables[name]:
            documented = (
                next(
                    (item for item in semantic_table.columns if item.name == column.name),
                    None,
                )
                if semantic_table is not None
                else None
            )
            description = ""
            if documented is not None:
                description = (
                    documented.description_es if language == "es" else documented.description_en
                )
            columns.append({"name": column.name, "type": column.type, "description": description})
        tables.append(
            {
                "name": name,
                "description": (
                    semantic_table.description_es
                    if semantic_table is not None and language == "es"
                    else semantic_table.description_en
                    if semantic_table is not None
                    else ""
                ),
                "columns": columns,
            }
        )
    info = state.warehouse.info()
    return templates.TemplateResponse(
        request,
        "_schema.html",
        _context(
            request,
            language,
            tables=tables,
            attribution=info.attribution,
            license=info.license,
            source_url=info.source_url,
        ),
    )


# -- chat --------------------------------------------------------------
async def _read_payload(request: Request) -> tuple[str, str]:
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    if content_type.startswith("application/json"):
        raw = json.loads(body or b"{}")
        payload: dict[str, Any] = raw if isinstance(raw, dict) else {}
    else:
        # HTMX and the no-JS form post `application/x-www-form-urlencoded`; parsing
        # it here keeps python-multipart out of the dependency set (D2).
        fields = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
        payload = {key: values[-1] for key, values in fields.items()}
    question = str(payload.get("question", ""))
    language = str(payload.get("lang", "auto"))
    return question, language


def _language_value(value: str) -> Language | None:
    normalized = value.strip().lower()
    if normalized in {"es", "en"}:
        return Language(normalized)
    return None


@router.post("/ask", response_class=HTMLResponse)
async def ask(request: Request) -> HTMLResponse:
    state = _state(request)
    question, language_value = await _read_payload(request)
    language = _language_value(language_value)
    ui_language = _ui_language(request)
    record = state.store.create(question, language, ui_language)
    threading.Thread(target=_execute_run, args=(state, record), daemon=True).start()
    return HTMLResponse(
        render_template(
            "_pending.html",
            **_fragment_context(
                ui_language,
                run_id=record.id,
                question=question,
                steps=_initial_steps(ui_language),
            ),
        )
    )


def _execute_run(state: WebState, record: Any) -> None:
    """Run one agent request in its own thread and feed the SSE queue."""

    sink = ThreadEventSink(
        record.queue,
        lambda name, event: _render_event(state, record, name, event),
    )
    try:
        assert state.ask is not None  # noqa: S101 - set in WebState.__post_init__
        answer = state.ask.execute(
            record.question,
            None,
            language=record.language,
            sink=sink,
        )
    except Exception as exc:  # the agent should not raise; never leave a stream hanging
        logger.exception("web.run_failed", run_id=record.id, error_type=type(exc).__name__)
        answer = AgentAnswer(
            status=Status.FAILED,
            language=record.language or Language.EN,
            text=(
                "No pude completar la consulta. Revisa el backend con `sqlagent doctor`."
                if normalize_language(record.ui_language) == "es"
                else "I could not complete the query. Check the backend with `sqlagent doctor`."
            ),
        )
    state.store.complete(record.id, answer)
    try:
        record.queue.put(("answer", _render_answer_body(state, record, answer)))
        record.queue.put(("done", ""))
    finally:
        record.queue.put(None)


@router.get("/ask/stream/{run_id}")
async def stream(request: Request, run_id: str) -> Response:
    state = _state(request)
    record = state.store.get(run_id)
    if record is None:
        return JSONResponse({"error": "unknown run"}, status_code=404)

    async def events() -> AsyncIterator[str]:
        while True:
            item = await run_in_threadpool(record.queue.get)
            if item is None:
                break
            name, data = item
            yield format_sse(name, data)
            if name == "done":
                break

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/ask")
async def api_ask(request: Request) -> Response:
    state = _state(request)
    content_type = request.headers.get("content-type", "")
    wants_html = "text/html" in request.headers.get("accept", "") and not content_type.startswith(
        "application/json"
    )
    question, language_value = await _read_payload(request)
    language = _language_value(language_value)
    ui_language = _ui_language(request)
    record = state.store.create(question, language, ui_language)
    assert state.ask is not None  # noqa: S101 - set in WebState.__post_init__
    answer = await run_in_threadpool(
        state.ask.execute,
        question,
        None,
        language=language,
    )
    state.store.complete(record.id, answer)
    if wants_html:
        return templates.TemplateResponse(
            request,
            "index.html",
            _context(
                request,
                ui_language,
                initial_answer=answer,
                answer_id=record.id,
                initial_question=question,
            ),
        )
    body = answer_to_dict(answer)
    body["answer_id"] = record.id
    return JSONResponse(body)


@router.get("/export/{answer_id}.csv")
async def export_csv(request: Request, answer_id: str) -> Response:
    state = _state(request)
    record = state.store.get(answer_id)
    if record is None or record.answer is None or record.answer.result is None:
        return JSONResponse({"error": "unknown answer"}, status_code=404)
    result = record.answer.result
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([column.name for column in result.columns])
    for row in result.rows:
        writer.writerow(["" if value is None else value for value in row])
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="answer-{answer_id}.csv"',
            "Cache-Control": "no-store",
        },
    )


# -- fragment rendering ------------------------------------------------
def _render_event(  # noqa: PLR0911 - one branch per SSE event type
    state: WebState,
    record: Any,
    name: str,
    event: AgentEvent,
) -> str:
    language = normalize_language(record.ui_language)
    if name == "phase":
        phase = event.phase.value if event.phase is not None else "UNDERSTAND"
        return render_template(
            "_stepper.html",
            **_fragment_context(language, run_id=record.id, steps=_steps(phase, language)),
        )
    if name == "retrieval":
        tables = [str(table) for table in event.payload.get("tables", ())]
        return render_template(
            "_retrieval.html",
            **_fragment_context(language, tables=tables),
        )
    if name == "sql":
        return render_template(
            "_sql.html",
            **_fragment_context(language, sql=str(event.payload.get("sql", ""))),
        )
    if name == "result":
        payload = dict(event.payload)
        record.extras["result"] = payload
        return _render_result(language, payload)
    if name == "chart":
        spec = dict(event.payload)
        result_payload = record.extras.get("result")
        if not isinstance(result_payload, dict):
            return ""
        return _render_chart(language, spec, result_payload)
    if name == "error":
        return render_template(
            "_error.html",
            **_fragment_context(
                language,
                category=str(event.payload.get("category", "error")),
                error_hint=translate(language, "error_hint"),
            ),
        )
    return ""


def _render_result(language: str, payload: dict[str, Any]) -> str:
    rows = list(payload.get("rows", ()))
    return render_template(
        "_result.html",
        **_fragment_context(
            language,
            columns=list(payload.get("columns", ())),
            rows=rows,
            row_count=int(payload.get("row_count", len(rows))),
            truncated=bool(payload.get("truncated", False)),
        ),
    )


def _render_chart(
    language: str,
    spec: dict[str, Any],
    result_payload: dict[str, Any],
) -> str:
    columns = list(result_payload.get("columns", ()))
    rows = list(result_payload.get("rows", ()))
    chart_data = {"spec": spec, "columns": columns, "rows": rows}
    y_names = [str(name) for name in spec.get("y", ())]
    index = next(
        (
            position
            for position, column in enumerate(columns)
            if str(column.get("name")) == (y_names[0] if y_names else "")
        ),
        0,
    )
    kpi_value = rows[0][index] if rows and rows[0] else ""
    return render_template(
        "_chart.html",
        **_fragment_context(language, chart_data=chart_data, kpi_value=kpi_value),
    )


def _render_answer_body(state: WebState, record: Any, answer: AgentAnswer) -> str:
    language = normalize_language(record.ui_language)
    return render_template(
        "_answer_body.html",
        **_fragment_context(
            language,
            answer=answer,
            answer_id=record.id,
            limit=state.settings.max_rows,
            ui_rows=state.settings.ui_rows,
            exported=answer.result is not None,
        ),
    )


__all__ = ["PHASE_ORDER", "router"]
