"""Rich CLI rendering and JSON serialisation of ``AgentAnswer`` (D25).

The JSON form is the contract used by scripts and the installer smoke test; the
rich form is the human view.  Both are pure functions of the answer, so the CLI
never reaches into the agent internals.
"""

from __future__ import annotations

import json

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from sqlagent.domain.models import AgentAnswer, QueryResult

_MAX_TABLE_ROWS = 20
_SPARKLINE = "▁▂▃▄▅▆▇█"


def answer_to_dict(answer: AgentAnswer) -> dict[str, object]:
    """Return a JSON-safe representation of an answer (one document)."""

    result: dict[str, object] | None = None
    if answer.result is not None:
        result = {
            "columns": [
                {"name": column.name, "type": column.type} for column in answer.result.columns
            ],
            "rows": [list(row) for row in answer.result.rows],
            "row_count": answer.result.row_count,
            "truncated": answer.result.truncated,
        }
    chart: dict[str, object] | None = None
    if answer.chart is not None:
        chart = {
            "kind": answer.chart.kind,
            "x": answer.chart.x,
            "y": list(answer.chart.y),
            "series": answer.chart.series,
            "title": answer.chart.title,
            "reason": answer.chart.reason,
            "truncated_categories": answer.chart.truncated_categories,
        }
    trace = answer.trace
    return {
        "status": answer.status,
        "language": answer.language,
        "text": answer.text,
        "sql": answer.sql,
        "result": result,
        "chart": chart,
        "trace": {
            "phases": [
                {"phase": phase.phase, "elapsed_ms": phase.elapsed_ms} for phase in trace.phases
            ],
            "attempts": [
                {
                    "kind": attempt.kind,
                    "sql": attempt.sql,
                    "error_code": attempt.error_code,
                    "error_message": attempt.error_message,
                }
                for attempt in trace.attempts
            ],
            "retrieved_tables": list(trace.retrieved_tables),
            "tool_calls": trace.tool_calls,
            "guardrail_events": list(trace.guardrail_events),
            "injection_flags": trace.injection_flags,
            "usage": {
                "prompt": trace.usage.prompt,
                "completion": trace.usage.completion,
                "total": trace.usage.total,
            },
            "llm_calls": trace.llm_calls,
        },
    }


def answer_to_json(answer: AgentAnswer) -> str:
    """Serialise an answer as exactly one JSON document."""

    return json.dumps(answer_to_dict(answer), ensure_ascii=False, default=str)


def render_answer(
    answer: AgentAnswer,
    *,
    trace: bool = False,
    console: Console | None = None,
) -> None:
    """Print the answer, SQL, result table, chart and optional trace."""

    out = console or Console()
    title = {
        "ok": "Answer",
        "clarification": "Clarification",
        "refused": "Refused",
        "failed": "Failed",
    }.get(answer.status.value, "Answer")
    out.print(Panel(answer.text, title=f"{title} ({answer.language.value})"))

    if answer.sql:
        out.print(Panel(Syntax(answer.sql, "sql", word_wrap=True), title="SQL"))
    if answer.result is not None:
        out.print(_render_result(answer.result))
    if answer.chart is not None:
        chart = _render_chart(answer)
        if chart is not None:
            out.print(Panel(chart, title=f"Chart ({answer.chart.kind})"))
    if trace:
        out.print(_render_trace(answer))


def _render_result(result: QueryResult) -> Table:
    title = f"Result ({result.row_count} rows)"
    table = Table(title=title, min_width=len(title) + 4)
    for column in result.columns:
        table.add_column(column.name, overflow="fold")
    for row in result.rows[:_MAX_TABLE_ROWS]:
        table.add_row(*(("NULL" if value is None else str(value)) for value in row))
    if result.row_count > _MAX_TABLE_ROWS:
        table.caption = f"showing {_MAX_TABLE_ROWS} of {result.row_count} rows"
    return table


def _render_chart(answer: AgentAnswer) -> str | None:  # noqa: PLR0911 - one per chart kind
    chart = answer.chart
    result = answer.result
    if chart is None or result is None or not chart.y:
        return None
    y_index = next(
        (index for index, column in enumerate(result.columns) if column.name == chart.y[0]),
        None,
    )
    if y_index is None:
        return None
    values = [row[y_index] for row in result.rows]
    if chart.kind == "kpi":
        return f"{chart.y[0]}: {values[0] if values else 'NULL'}"
    if chart.kind in {"bar", "hbar"}:
        numeric = [float(value) for value in values if isinstance(value, (int, float))]
        if not numeric:
            return None
        peak = max(numeric) or 1.0
        labels = result.rows
        lines = []
        for row, value in zip(labels, values, strict=False):
            label = str(row[0])[:28]
            amount = float(value) if isinstance(value, (int, float)) else 0.0
            bars = "█" * max(1, round(24 * amount / peak))
            lines.append(f"{label:<28} {bars} {value}")
        return "\n".join(lines)
    if chart.kind == "line":
        numeric = [float(value) for value in values if isinstance(value, (int, float))]
        if not numeric:
            return None
        low, high = min(numeric), max(numeric)
        span = (high - low) or 1.0
        top = len(_SPARKLINE) - 1
        points = [_SPARKLINE[min(top, round((value - low) / span * top))] for value in numeric]
        return "".join(points)
    return None


def _render_trace(answer: AgentAnswer) -> Panel:
    table = Table(title="Trace")
    table.add_column("field")
    table.add_column("value", overflow="fold")
    trace = answer.trace
    table.add_row("llm_calls", str(trace.llm_calls))
    table.add_row("tool_calls", str(trace.tool_calls))
    table.add_row("tokens", f"{trace.usage.total} ({trace.usage.prompt}+{trace.usage.completion})")
    table.add_row("retrieved_tables", ", ".join(trace.retrieved_tables) or "-")
    table.add_row("attempts", str(len(trace.attempts)))
    for attempt in trace.attempts:
        table.add_row(
            f"attempt {attempt.kind}",
            f"{attempt.error_code or 'ok'}: {attempt.sql[:80]}",
        )
    table.add_row("guardrails", ", ".join(trace.guardrail_events) or "-")
    table.add_row("injection_flags", str(trace.injection_flags))
    phases = ", ".join(f"{phase.phase}={phase.elapsed_ms:.0f}ms" for phase in trace.phases)
    table.add_row("phases", phases or "-")
    return Panel(table, title="Trace")


__all__ = ["answer_to_dict", "answer_to_json", "render_answer"]
