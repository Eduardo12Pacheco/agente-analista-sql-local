"""Inline SVG chart primitives for the self-contained HTML report (S25).

The output is a plain ``<svg>`` fragment with no scripts, no external assets and
no external URLs.  Colours are CSS custom properties supplied by the report's
stylesheet, which gives the light/dark theme for free.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape


def _labels(labels: Sequence[str], limit: int = 13) -> list[str]:
    return [label if len(label) <= limit else label[: limit - 1] + "…" for label in labels]


def bar_chart(  # noqa: PLR0913 - layout knobs are explicit
    labels: Sequence[str],
    values: Sequence[float],
    *,
    title: str = "",
    width: int = 520,
    height: int = 240,
    value_format: str = "{:.2f}",
) -> str:
    """Render a vertical bar chart; returns ``""`` when there is no data."""

    pairs = [(str(label), float(value)) for label, value in zip(labels, values, strict=False)]
    if not pairs:
        return ""
    left, right, top, bottom = 36, 12, 28, 58
    plot_width = max(1, width - left - right)
    plot_height = max(1, height - top - bottom)
    maximum = max((value for _, value in pairs), default=0.0)
    scale = maximum if maximum > 0 else 1.0
    slot = plot_width / len(pairs)
    bar_width = max(4.0, slot * 0.62)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" '
        f'width="100%" role="img" aria-label="{escape(title)}">',
        f"<title>{escape(title)}</title>",
        f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" '
        f'y2="{height - bottom}" stroke="var(--border)" stroke-width="1"/>',
    ]
    for index, (label, value) in enumerate(pairs):
        x = left + slot * index + (slot - bar_width) / 2
        bar_height = max(1.0, plot_height * value / scale) if value > 0 else 0.0
        y = height - bottom - bar_height
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
            f'height="{bar_height:.1f}" rx="3" fill="var(--accent)"/>'
        )
        parts.append(
            f'<text x="{x + bar_width / 2:.1f}" y="{max(top - 6, y - 6):.1f}" '
            f'text-anchor="middle" font-size="10" fill="var(--muted)">'
            f"{escape(value_format.format(value))}</text>"
        )
        parts.append(
            f'<text x="{x + bar_width / 2:.1f}" y="{height - bottom + 16}" '
            f'text-anchor="end" font-size="10" fill="var(--muted)" '
            f'transform="rotate(-30 {x + bar_width / 2:.1f} {height - bottom + 16})">'
            f"{escape(_labels([label])[0])}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def histogram(
    values: Sequence[float],
    *,
    bins: int = 8,
    title: str = "Latency distribution",
) -> str:
    """Render a nearest-range histogram of per-question latencies in ms."""

    data = [float(value) for value in values]
    if not data:
        return ""
    low, high = min(data), max(data)
    count = max(1, bins)
    if high <= low:
        return bar_chart([f"{low:.0f} ms"], [float(len(data))], title=title, value_format="{:.0f}")
    step = (high - low) / count
    counts = [0] * count
    for value in data:
        index = min(count - 1, int((value - low) / step))
        counts[index] += 1
    labels = [
        f"{low + step * index:.0f}-{low + step * (index + 1):.0f} ms" for index in range(count)
    ]
    return bar_chart(labels, [float(value) for value in counts], title=title, value_format="{:.0f}")


__all__ = ["bar_chart", "histogram"]
