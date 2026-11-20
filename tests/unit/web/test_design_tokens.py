"""Design tokens must match D23 and meet WCAG AA contrast in both themes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

CSS_PATH = Path(__file__).resolve().parents[3] / "src/sqlagent/adapters/web/static/app.css"

LIGHT = {
    "bg": "#f7f7f5",
    "surface": "#ffffff",
    "text": "#1b1f24",
    "muted": "#565d66",
    "accent": "#0b5cad",
    "border": "#d9dce1",
    "danger": "#b42318",
    "success": "#067647",
    "code-bg": "#f1f3f5",
}
DARK = {
    "bg": "#0f1419",
    "surface": "#171d24",
    "text": "#e8ecf1",
    "muted": "#a3acb8",
    "accent": "#6cb2ff",
    "border": "#2a323c",
    "danger": "#ff8a7a",
    "success": "#5bd69a",
    "code-bg": "#1d252e",
}


def _relative_luminance(hex_color: str) -> float:
    raw = hex_color.lstrip("#")
    channels = [int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4)]

    def linear(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    high, low = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _block(css: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{", css)
    assert match is not None, f"missing CSS block {selector}"
    start = match.end() - 1
    depth = 0
    for index in range(start, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[start + 1 : index]
    raise AssertionError(f"unterminated CSS block {selector}")


def _tokens(block: str) -> dict[str, str]:
    return {
        name: value.lower()
        for name, value in re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", block)
    }


def _assert_palette(tokens: dict[str, str], expected: dict[str, str]) -> None:
    for name, value in expected.items():
        assert tokens.get(name) == value, f"token --{name} drifted from D23"


def test_light_palette_matches_d23() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    _assert_palette(_tokens(_block(css, ":root")), LIGHT)


def test_dark_palette_matches_d23() -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    _assert_palette(_tokens(_block(css, '[data-theme="dark"]')), DARK)
    media = _block(css, "@media (prefers-color-scheme: dark)")
    nested = _block(media, ":root")
    _assert_palette(_tokens(nested), DARK)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("text", "surface"),
        ("muted", "surface"),
        ("accent", "surface"),
        ("accent-contrast", "accent"),
    ],
)
def test_light_theme_contrast_meets_wcag_aa(first: str, second: str) -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    tokens = _tokens(_block(css, ":root"))
    assert contrast(tokens[first], tokens[second]) >= 4.5, f"{first}/{second}"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("text", "surface"),
        ("muted", "surface"),
        ("accent", "surface"),
        ("accent-contrast", "accent"),
    ],
)
def test_dark_theme_contrast_meets_wcag_aa(first: str, second: str) -> None:
    css = CSS_PATH.read_text(encoding="utf-8")
    tokens = _tokens(_block(css, '[data-theme="dark"]'))
    assert contrast(tokens[first], tokens[second]) >= 4.5, f"{first}/{second}"
