"""Markdown/HTML report rendering and the ``ReportWriter`` adapter (S25).

Both renderers read only the :class:`EvalSummary`; the writer additionally
persists the machine-readable artifacts.  No number is invented here: every
value comes from ``summary.metrics`` and every failing question from
``summary.items``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlagent.adapters.reporting.html import render_html
from sqlagent.application.evaluation.metrics import ItemResult
from sqlagent.application.evaluation.summary import EvalSummary

SERCOP_URL = "https://datosabiertos.compraspublicas.gob.ec"
LICENCE_URL = "https://creativecommons.org/licenses/by/3.0/ec/"


def _pct(value: Any) -> str:
    return f"{float(value) * 100:.1f}%" if isinstance(value, (int, float)) else "-"


def _num(value: Any, digits: int = 1) -> str:
    return f"{float(value):.{digits}f}" if isinstance(value, (int, float)) else "-"


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _failure_rows(summary: EvalSummary) -> list[ItemResult]:
    return [item for item in summary.items if not item.expected_ok]


def _metadata_lines(summary: EvalSummary) -> list[str]:
    model = summary.model
    environment = summary.environment
    config = summary.config
    return [
        f"- **Run id:** `{summary.run_id}`",
        f"- **Created at:** {summary.created_at}",
        f"- **Benchmark:** {summary.benchmark}",
        f"- **Model:** {model.get('name') or '-'} "
        f"(`{model.get('backend') or '-'}`, digest `{model.get('digest') or '-'}`)",
        f"- **Configuration:** narration={config.get('narrate')}, "
        f"retrieval={config.get('retrieval')}, max_repairs={config.get('max_repairs')}, "
        f"temperature={config.get('temperature')}, seed={config.get('seed')}",
        f"- **Environment:** {environment.get('os') or '-'}; "
        f"CPU: {environment.get('processor') or '-'}; GPU: {environment.get('gpu') or 'n/a'}; "
        f"Python {environment.get('python') or '-'}",
        "- **Warehouse manifest SHA-256:** "
        f"`{environment.get('warehouse_manifest_sha256') or '-'}`",
    ]


def _overall_table(metrics: dict[str, Any]) -> list[str]:
    overall = metrics.get("overall", {})
    latency = overall.get("latency_ms", {})
    tokens = overall.get("tokens", {})
    rows = [
        ("Answerable items", str(overall.get("n", 0))),
        ("Execution accuracy (EX)", _pct(overall.get("ex"))),
        (
            "EX Wilson 95% CI",
            f"[{_pct(overall.get('ex_ci_low'))}, {_pct(overall.get('ex_ci_high'))}]",
        ),
        ("Valid SQL rate", _pct(overall.get("valid_sql_rate"))),
        ("First-attempt EX", _pct(overall.get("first_attempt_ex"))),
        ("Repair uplift", f"{float(overall.get('repair_uplift', 0)) * 100:+.1f} pts"),
        ("Refusal accuracy", _pct(overall.get("refusal_acc"))),
        ("Clarification accuracy", _pct(overall.get("clarification_acc"))),
        ("Unanswerable accuracy", _pct(overall.get("unanswerable_acc"))),
        ("Pair consistency", _pct(overall.get("pair_consistency"))),
        ("Retrieval table recall", _pct(overall.get("retrieval_table_recall"))),
        ("Mean attempts", _num(overall.get("mean_attempts"), 2)),
        (
            "Latency mean / p50 / p95 (ms)",
            f"{_num(latency.get('mean'))} / {_num(latency.get('p50'))} / "
            f"{_num(latency.get('p95'))}",
        ),
        (
            "Tokens per question (prompt + completion)",
            f"{_num(tokens.get('prompt_per_question'))} + "
            f"{_num(tokens.get('completion_per_question'))}",
        ),
    ]
    return ["| Metric | Value |", "|---|---|", *[f"| {name} | {value} |" for name, value in rows]]


def _breakdown_table(title: str, buckets: dict[str, Any]) -> list[str]:
    lines = [
        f"### {title}",
        "",
        "| Group | Items | Answerable | EX | 95% CI | Expectation accuracy |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for name, bucket in buckets.items():
        low = _pct(bucket.get("ex_ci_low"))
        high = _pct(bucket.get("ex_ci_high"))
        lines.append(
            f"| {_cell(name)} | {bucket.get('n', 0)} | {bucket.get('n_answerable', 0)} | "
            f"{_pct(bucket.get('ex'))} | [{low}, {high}] | "
            f"{_pct(bucket.get('expectation_acc'))} |"
        )
    return lines


def render_markdown(summary: EvalSummary) -> str:
    """Render the human report (``report.md``)."""

    metrics: dict[str, Any] = dict(summary.metrics)
    lines = [
        f"# Evaluation report — {summary.run_id}",
        "",
        *_metadata_lines(summary),
        "",
        "## Overall metrics",
        "",
        *_overall_table(metrics),
        "",
        "## Execution accuracy by category",
        "",
        *_breakdown_table("Categories", metrics.get("by_category", {})),
        "",
        "## Execution accuracy by language",
        "",
        *_breakdown_table("Languages", metrics.get("by_language", {})),
        "",
        "## Execution accuracy by difficulty",
        "",
        *_breakdown_table("Difficulty", metrics.get("by_difficulty", {})),
        "",
        "## Failure taxonomy",
        "",
    ]
    taxonomy = metrics.get("failure_taxonomy", {})
    if taxonomy:
        lines.extend(["| Failure | Count |", "|---|---:|"])
        lines.extend(f"| {_cell(name)} | {count} |" for name, count in taxonomy.items())
    else:
        lines.append("No failures.")
    failures = _failure_rows(summary)
    lines.extend(["", "## Failing questions", ""])
    if not failures:
        lines.append("No failing questions.")
    else:
        lines.extend(
            [
                "| Id | Question | Status | Failure | Predicted SQL | Gold SQL |",
                "|---|---|---|---|---|---|",
            ]
        )
        for item in failures:
            lines.append(
                f"| {item.id} | {_cell(item.question)} | {_cell(item.status)} | "
                f"{_cell(item.failure or '-')} | {_cell(item.sql or '-')} | "
                f"{_cell(item.gold_sql or '-')} |"
            )
    lines.extend(
        [
            "",
            "---",
            "",
            "Data: SERCOP Ecuador OCDS 2021, CC BY 3.0 Ecuador "
            f"([source]({SERCOP_URL}), [licence]({LICENCE_URL})).",
            f"Schema: `{summary.schema}`.",
            "",
        ]
    )
    return "\n".join(lines)


class MarkdownHtmlReportWriter:
    """Write the four S25 artifacts for one evaluation run."""

    def write(
        self,
        summary: EvalSummary,
        results: Sequence[ItemResult],
        out_dir: Path,
    ) -> None:
        directory = Path(out_dir)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "summary.json").write_text(summary.to_json(), encoding="utf-8")
        (directory / "results.jsonl").write_text(summary.results_jsonl(), encoding="utf-8")
        (directory / "report.md").write_text(render_markdown(summary), encoding="utf-8")
        (directory / "report.html").write_text(render_html(summary), encoding="utf-8")


__all__ = ["MarkdownHtmlReportWriter", "render_markdown"]
