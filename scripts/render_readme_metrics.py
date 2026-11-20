"""Render the README/EVAL metrics tables from an evaluation summary (D33/S27).

The README results table and the ``docs/EVAL.md`` results must be generated from
a committed ``summary.json`` so no number is ever typed by hand.  This script
emits the canonical Markdown block that sits between the
``<!-- METRICS:START -->`` / ``<!-- METRICS:END -->`` markers in ``README.md`` and
``README.es.md``, and can verify that the committed copy matches the summary.

Usage::

    uv run python scripts/render_readme_metrics.py
    uv run python scripts/render_readme_metrics.py --breakdowns
    uv run python scripts/render_readme_metrics.py --write README.md README.es.md
    uv run python scripts/render_readme_metrics.py --check README.md README.es.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

START_MARKER = "<!-- METRICS:START -->"
END_MARKER = "<!-- METRICS:END -->"
DEFAULT_SUMMARY = Path("eval/reports/latest/summary.json")


def load_summary(path: Path) -> dict[str, Any]:
    """Load and minimally validate a ``sqlagent.eval-summary/v1`` document."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"error: cannot read summary {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: summary {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != "sqlagent.eval-summary/v1":
        raise SystemExit(f"error: {path} is not a sqlagent.eval-summary/v1 document")
    return data


def _pct(value: Any) -> str:
    return f"{float(value) * 100:.1f}%"


def _float(value: Any, digits: int = 1) -> str:
    return f"{float(value):.{digits}f}"


def environment_line(summary: dict[str, Any]) -> str:
    """Return the D33 provenance line printed under the metrics table."""

    model = summary.get("model", {})
    env = summary.get("environment", {})
    name = model.get("name", "unknown")
    digest = model.get("digest") or "unknown"
    gpu = env.get("gpu") or "CPU"
    os_name = env.get("os", "unknown")
    created = summary.get("created_at", "unknown")
    return (
        f"Model `{name}` (digest `{digest}`) on {gpu}, {os_name}; "
        f"run `{summary.get('run_id', 'unknown')}` on {created}; n = "
        f"{summary.get('metrics', {}).get('overall', {}).get('included', '?')}."
    )


def overall_table(summary: dict[str, Any]) -> str:
    """Return the compact results table used by both READMEs (D32/D33)."""

    overall = summary["metrics"]["overall"]
    latency = overall["latency_ms"]
    tokens = overall["tokens"]
    rows = [
        (
            "Execution accuracy (EX)",
            f"{_pct(overall['ex'])} [{_pct(overall['ex_ci_low'])}, {_pct(overall['ex_ci_high'])}]",
        ),
        ("Valid SQL rate", _pct(overall["valid_sql_rate"])),
        ("First-attempt EX", _pct(overall["first_attempt_ex"])),
        ("Repair uplift", f"{float(overall['repair_uplift']) * 100:+.1f} pts"),
        ("Refusal accuracy", _pct(overall["refusal_acc"])),
        ("Latency p50 / p95", f"{_float(latency['p50'], 0)} ms / {_float(latency['p95'], 0)} ms"),
        (
            "Tokens per question",
            f"{_float(tokens['prompt_per_question'], 0)} prompt / "
            f"{_float(tokens['completion_per_question'], 0)} completion",
        ),
    ]
    table = ["| Metric | Result |", "|---|---|"]
    table.extend(f"| {label} | {value} |" for label, value in rows)
    table.append("")
    table.append(environment_line(summary))
    return "\n".join(table)


def _breakdown_table(title: str, bucket: dict[str, Any], label: str) -> str:
    rows = ["| " + label + " | EX | 95% CI | n |", "|---|---|---|---|"]
    for key, values in bucket.items():
        rows.append(
            f"| {key} | {_pct(values['ex'])} | "
            f"[{_pct(values['ex_ci_low'])}, {_pct(values['ex_ci_high'])}] | {values['n']} |"
        )
    return "\n".join([f"**{title}**", "", *rows])


def breakdown_tables(summary: dict[str, Any]) -> str:
    """Return the per-category/language/difficulty tables for ``docs/EVAL.md``."""

    metrics = summary["metrics"]
    sections = [
        _breakdown_table("By category", metrics["by_category"], "Category"),
        _breakdown_table("By language", metrics["by_language"], "Language"),
        _breakdown_table("By difficulty", metrics["by_difficulty"], "Difficulty"),
    ]
    taxonomy = metrics.get("failure_taxonomy") or {}
    if taxonomy:
        rows = ["| Failure mode | Count |", "|---|---|"]
        rows.extend(f"| {key} | {value} |" for key, value in taxonomy.items())
        sections.append("\n".join(["**Failure taxonomy**", "", *rows]))
    return "\n\n".join(sections)


def render(summary: dict[str, Any], *, breakdowns: bool = False) -> str:
    """Return the Markdown block that belongs between the markers."""

    block = overall_table(summary)
    if breakdowns:
        block = f"{block}\n\n{breakdown_tables(summary)}"
    return block


def _replace_block(text: str, block: str) -> str:
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise SystemExit(f"error: markers {START_MARKER} / {END_MARKER} not found in document")
    return f"{text[: start + len(START_MARKER)]}\n{block}\n{text[end:]}"


def _current_block(text: str) -> str:
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise SystemExit(f"error: markers {START_MARKER} / {END_MARKER} not found in document")
    return text[start + len(START_MARKER) : end].strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument(
        "--breakdowns",
        action="store_true",
        help="also print the per-category/language/difficulty tables",
    )
    parser.add_argument(
        "--write",
        nargs="+",
        type=Path,
        metavar="DOC",
        help="replace the marked block in each document",
    )
    parser.add_argument(
        "--check",
        nargs="+",
        type=Path,
        metavar="DOC",
        help="exit 1 when a document's marked block differs from the summary",
    )
    args = parser.parse_args(argv)

    summary = load_summary(args.summary)
    block = render(summary, breakdowns=args.breakdowns)

    if args.write:
        for path in args.write:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                print(f"error: cannot read {path}: {exc}", file=sys.stderr)
                return 2
            path.write_text(_replace_block(text, block) + "\n", encoding="utf-8")
            print(f"updated {path}")

    if args.check:
        failed = False
        for path in args.check:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                print(f"error: cannot read {path}: {exc}", file=sys.stderr)
                return 2
            if _current_block(text) != block:
                print(f"stale metrics in {path}: run this script with --write", file=sys.stderr)
                failed = True
        if failed:
            return 1

    if not args.write and not args.check:
        print(block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
