"""Unit tests for the Markdown/HTML reports and inline SVG charts (S25)."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from sqlagent.adapters.reporting.html import render_html
from sqlagent.adapters.reporting.markdown import MarkdownHtmlReportWriter, render_markdown
from sqlagent.adapters.reporting.svg import bar_chart, histogram
from sqlagent.application.evaluation.metrics import ItemResult, aggregate_metrics
from sqlagent.application.evaluation.summary import build_summary

pytestmark = pytest.mark.unit

ALLOWED_EXTERNAL_URLS = {
    "https://datosabiertos.compraspublicas.gob.ec",
    "https://creativecommons.org/licenses/by/3.0/ec/",
}


def _item(
    item_id: str,
    *,
    ex: bool,
    failure: str | None = None,
    sql: str = "SELECT 1 AS n",
    gold_sql: str = "SELECT 1 AS n",
) -> ItemResult:
    return ItemResult(
        id=item_id,
        category="aggregation",
        difficulty="easy",
        lang="en",
        expect="answer",
        question=f"Question {item_id}?",
        status="ok" if ex else "failed",
        sql=sql,
        gold_sql=gold_sql,
        executed=True,
        ex=ex,
        expected_ok=ex,
        first_attempt_ex=ex,
        valid_sql=True,
        attempts=1,
        failure=None if ex else (failure or "wrong_result"),
        latency_ms=10.0 if ex else 30.0,
        prompt_tokens=100,
        completion_tokens=20,
        retrieved_tables=("tenders",),
        gold_tables=("tenders",),
        guardrail_events=(),
        pair_id=None,
    )


def sample_summary():
    items = (
        _item("q001", ex=True),
        _item(
            "q002",
            ex=False,
            sql="SELECT 0 AS n",
            gold_sql="SELECT COUNT(*) AS n FROM tenders",
        ),
    )
    metrics = aggregate_metrics(items)
    return build_summary(
        benchmark="v1",
        run_id="20261120T000000Z-oracle",
        created_at="2026-11-20T00:00:00+00:00",
        model={"name": "oracle", "digest": "oracle-v1", "backend": "oracle"},
        config={"narrate": False, "retrieval": True, "max_repairs": 2},
        environment={"os": "Linux", "python": "3.12", "gpu": None},
        metrics=metrics,
        items=items,
    )


def external_urls(text: str) -> set[str]:
    matches = re.findall(r"https?://[^\s\"'<>)]+", text)
    return {match.rstrip(".,") for match in matches}


def test_svg_charts_are_self_contained_and_escape_labels() -> None:
    chart = bar_chart(["<script>", "join"], [0.5, 1.0], title="EX <by> category")
    assert chart.startswith("<svg")
    assert "&lt;script&gt;" in chart
    assert "<script>" not in chart
    assert "http://" not in chart and "https://" not in chart
    empty = bar_chart([], [])
    assert empty == ""
    hist = histogram([1.0, 2.0, 3.0, 10.0], bins=4)
    assert hist.startswith("<svg")
    assert "ms" in hist


def test_markdown_report_contains_metrics_and_failure_table() -> None:
    text = render_markdown(sample_summary())
    assert "# Evaluation report" in text
    assert "Execution accuracy" in text
    assert "| aggregation |" in text
    assert "q002" in text
    assert "SELECT 0 AS n" in text
    assert "wrong_result" in text
    assert "sqlagent.eval-summary/v1" in text


def test_html_report_is_self_contained_with_allowed_links_only() -> None:
    text = render_html(sample_summary())
    assert text.startswith("<!doctype html>")
    assert "<svg" in text
    assert "prefers-color-scheme: dark" in text
    assert "q002" in text
    assert external_urls(text) <= ALLOWED_EXTERNAL_URLS


def test_html_report_escapes_untrusted_text() -> None:
    summary = sample_summary()
    dangerous = "<script>alert(1)</script>"
    items = tuple(replace(item, question=dangerous) for item in summary.items)
    escaped = build_summary(
        benchmark=summary.benchmark,
        run_id=summary.run_id,
        created_at=summary.created_at,
        model=summary.model,
        config=summary.config,
        environment=summary.environment,
        metrics=summary.metrics,
        items=items,
    )
    text = render_html(escaped)
    assert "<script>alert(1)</script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text


def test_report_writer_writes_four_files(tmp_path) -> None:
    summary = sample_summary()
    writer = MarkdownHtmlReportWriter()
    writer.write(summary, summary.items, tmp_path)
    names = {path.name for path in tmp_path.iterdir()}
    assert names == {"summary.json", "results.jsonl", "report.md", "report.html"}
    assert (tmp_path / "results.jsonl").read_text(encoding="utf-8").count("\n") == 2
