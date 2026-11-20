"""Server-side SQL highlighting: tokens, escaping and graceful fallback."""

from __future__ import annotations

import pytest

from sqlagent.adapters.web.highlight import highlight_sql

pytestmark = pytest.mark.unit


def test_highlights_keywords_functions_strings_numbers_and_identifiers() -> None:
    html = highlight_sql(
        "SELECT COUNT(*) AS n FROM tenders WHERE status = 'active' AND amount > 10.5"
    )

    assert 'class="tok-kw">SELECT<' in html
    assert 'class="tok-fn">COUNT<' in html
    assert "class=\"tok-str\">'active'<" in html
    assert 'class="tok-num">10.5<' in html
    assert 'class="tok-id">tenders<' in html


def test_escapes_html_in_literals() -> None:
    html = highlight_sql("SELECT '<script>alert(1)</script>' AS payload")

    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def test_never_raises_on_arbitrary_text() -> None:
    assert highlight_sql("not sql <>&\"'")  # returns escaped markup instead of raising
    assert highlight_sql("") == ""
