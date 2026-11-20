"""Self-contained HTML evaluation report with inline SVG charts (S25).

The document has no scripts, no external stylesheets and no external images; the
only external URLs are the SERCOP source and licence attribution links.  All
question text and SQL is escaped before rendering.
"""

from __future__ import annotations

from html import escape
from typing import Any

from sqlagent.adapters.reporting.svg import bar_chart, histogram
from sqlagent.application.evaluation.summary import EvalSummary

SERCOP_URL = "https://datosabiertos.compraspublicas.gob.ec"
LICENCE_URL = "https://creativecommons.org/licenses/by/3.0/ec/"

_CSS = """
:root {
  --bg: #f7f7f5; --surface: #ffffff; --text: #1b1f24; --muted: #565d66;
  --accent: #0b5cad; --border: #d9dce1; --danger: #b42318; --success: #067647;
  --code-bg: #f1f3f5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1419; --surface: #171d24; --text: #e8ecf1; --muted: #a3acb8;
    --accent: #6cb2ff; --border: #2a323c; --danger: #ff8a7a; --success: #5bd69a;
    --code-bg: #1d252e;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 16px; background: var(--bg); color: var(--text);
  font: 16px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 960px; margin: 0 auto; }
h1 { font-size: 1.7rem; margin: 0 0 8px; }
h2 { font-size: 1.25rem; margin-top: 32px; border-bottom: 1px solid var(--border); }
h3 { font-size: 1.05rem; margin-top: 24px; }
p, li { color: var(--text); }
.muted { color: var(--muted); }
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px 20px; margin: 16px 0;
}
table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.92rem; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 600; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
pre {
  background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px; overflow-x: auto; white-space: pre-wrap; font-size: 0.85rem;
}
details { border-bottom: 1px solid var(--border); padding: 8px 0; }
summary { cursor: pointer; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
.fail { color: var(--danger); }
footer { margin-top: 32px; color: var(--muted); font-size: 0.85rem; }
a { color: var(--accent); }
@media (max-width: 480px) { body { padding: 16px 10px; } }
"""


def _pct(value: Any) -> str:
    return f"{float(value) * 100:.1f}%" if isinstance(value, (int, float)) else "-"


def _num(value: Any, digits: int = 1) -> str:
    return f"{float(value):.{digits}f}" if isinstance(value, (int, float)) else "-"


def _breakdown_table(buckets: dict[str, Any]) -> str:
    rows = []
    for name, bucket in buckets.items():
        rows.append(
            "<tr>"
            f"<td>{escape(str(name))}</td>"
            f'<td class="num">{bucket.get("n", 0)}</td>'
            f'<td class="num">{bucket.get("n_answerable", 0)}</td>'
            f'<td class="num">{_pct(bucket.get("ex"))}</td>'
            f'<td class="num">[{_pct(bucket.get("ex_ci_low"))}, '
            f"{_pct(bucket.get('ex_ci_high'))}]</td>"
            f'<td class="num">{_pct(bucket.get("expectation_acc"))}</td>'
            "</tr>"
        )
    return (
        '<table><thead><tr><th>Group</th><th class="num">Items</th>'
        '<th class="num">Answerable</th><th class="num">EX</th>'
        '<th class="num">95% CI</th><th class="num">Expectation acc.</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _overall_table(metrics: dict[str, Any]) -> str:
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
            "Tokens per question",
            f"{_num(tokens.get('prompt_per_question'))} + "
            f"{_num(tokens.get('completion_per_question'))}",
        ),
    ]
    body = "".join(
        f'<tr><th>{escape(name)}</th><td class="num">{escape(str(value))}</td></tr>'
        for name, value in rows
    )
    return f"<table><tbody>{body}</tbody></table>"


def _failure_section(summary: EvalSummary) -> str:
    failures = [item for item in summary.items if not item.expected_ok]
    if not failures:
        return '<p class="muted">No failing questions.</p>'
    parts = ["<div>"]
    for item in failures:
        parts.append(
            "<details>"
            f"<summary><strong>{escape(item.id)}</strong> · "
            f'{escape(item.question)} · <span class="fail">'
            f"{escape(item.failure or item.status)}</span></summary>"
            f'<p class="muted">status={escape(item.status)} · '
            f"attempts={item.attempts} · category={escape(item.category)} · "
            f"lang={escape(item.lang)} · expect={escape(item.expect)}</p>"
            f"<p><strong>Predicted SQL</strong></p><pre>{escape(item.sql or '-')}</pre>"
            f"<p><strong>Gold SQL</strong></p><pre>{escape(item.gold_sql or '-')}</pre>"
            "</details>"
        )
    parts.append("</div>")
    return "".join(parts)


def _taxonomy_section(metrics: dict[str, Any]) -> str:
    taxonomy = metrics.get("failure_taxonomy", {})
    if not taxonomy:
        return '<p class="muted">No failures.</p>'
    rows = "".join(
        f'<tr><td>{escape(str(name))}</td><td class="num">{count}</td></tr>'
        for name, count in taxonomy.items()
    )
    return (
        '<table><thead><tr><th>Failure</th><th class="num">Count</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def render_html(summary: EvalSummary) -> str:
    """Render the self-contained ``report.html`` document."""

    metrics: dict[str, Any] = dict(summary.metrics)
    categories = metrics.get("by_category", {})
    languages = metrics.get("by_language", {})
    difficulties = metrics.get("by_difficulty", {})
    category_chart = bar_chart(
        list(categories),
        [float(bucket.get("ex", 0.0)) for bucket in categories.values()],
        title="Execution accuracy by category",
        value_format="{:.0%}",
    )
    language_chart = bar_chart(
        list(languages),
        [float(bucket.get("ex", 0.0)) for bucket in languages.values()],
        title="Execution accuracy by language",
        value_format="{:.0%}",
    )
    difficulty_chart = bar_chart(
        list(difficulties),
        [float(bucket.get("ex", 0.0)) for bucket in difficulties.values()],
        title="Execution accuracy by difficulty",
        value_format="{:.0%}",
    )
    latency_chart = histogram(
        [item.latency_ms for item in summary.items],
        title="Latency distribution (ms)",
    )
    model = summary.model
    environment = summary.environment
    config = summary.config
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Evaluation report — {escape(summary.run_id)}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>Evaluation report</h1>
<p class="muted">Run <code>{escape(summary.run_id)}</code> · {escape(summary.created_at)} ·
benchmark {escape(summary.benchmark)} · schema <code>{escape(summary.schema)}</code></p>
<div class="card">
<h2>Run metadata</h2>
<ul>
<li><strong>Model:</strong> {escape(str(model.get("name") or "-"))}
 (<code>{escape(str(model.get("backend") or "-"))}</code>, digest
 <code>{escape(str(model.get("digest") or "-"))}</code>)</li>
<li><strong>Configuration:</strong> narration={escape(str(config.get("narrate")))},
 retrieval={escape(str(config.get("retrieval")))},
 max_repairs={escape(str(config.get("max_repairs")))},
 temperature={escape(str(config.get("temperature")))},
 seed={escape(str(config.get("seed")))}</li>
<li><strong>Environment:</strong> {escape(str(environment.get("os") or "-"))};
 CPU {escape(str(environment.get("processor") or "-"))};
 GPU {escape(str(environment.get("gpu") or "n/a"))};
 Python {escape(str(environment.get("python") or "-"))}</li>
<li><strong>Warehouse manifest:</strong>
 <code>{escape(str(environment.get("warehouse_manifest_sha256") or "-"))}</code></li>
</ul>
</div>
<div class="card">
<h2>Overall metrics</h2>
{_overall_table(metrics)}
</div>
<div class="grid">
<div class="card"><h2>By category</h2>{category_chart}{_breakdown_table(categories)}</div>
<div class="card"><h2>By language</h2>{language_chart}{_breakdown_table(languages)}</div>
<div class="card"><h2>By difficulty</h2>{difficulty_chart}{_breakdown_table(difficulties)}</div>
<div class="card"><h2>Latency</h2>{latency_chart}</div>
</div>
<div class="card"><h2>Failure taxonomy</h2>{_taxonomy_section(metrics)}</div>
<div class="card"><h2>Failing questions</h2>{_failure_section(summary)}</div>
<footer>
Data: SERCOP Ecuador OCDS 2021, CC BY 3.0 Ecuador
(<a href="{SERCOP_URL}">source</a>, <a href="{LICENCE_URL}">licence</a>).
Generated by <code>sqlagent eval</code>.
</footer>
</main>
</body>
</html>
"""


__all__ = ["render_html"]
