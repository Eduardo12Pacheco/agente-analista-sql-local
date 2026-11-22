"""Bilingual UI dictionaries must stay in lockstep (S29/T10)."""

from __future__ import annotations

import pytest

from sqlagent.adapters.web.i18n import LANGUAGES, catalog, phase_label, translate
from sqlagent.adapters.web.templating import render_template

pytestmark = pytest.mark.unit

CHART_REASONS = (
    "category_breakdown",
    "category_breakdown_truncated",
    "no_rows",
    "not_chartable",
    "numeric_correlation",
    "single_value",
    "time_series",
)


def test_supported_languages() -> None:
    assert LANGUAGES == ("en", "es")


def test_dictionaries_have_identical_key_sets() -> None:
    english = catalog("en")
    spanish = catalog("es")

    assert set(english) == set(spanish)
    assert english


def test_no_blank_translations() -> None:
    for language in LANGUAGES:
        for key, value in catalog(language).items():
            assert value.strip(), f"{language}:{key} is blank"


def test_translate_formats_placeholders() -> None:
    assert "3" in translate("es", "rows_count", count=3)
    assert "3" in translate("en", "rows_count", count=3)
    assert translate("es", "rows_count", count=3) != translate("es", "rows_count", count=4)


def test_unknown_language_falls_back_to_english() -> None:
    assert translate("fr", "send") == translate("en", "send")


def test_unknown_key_returns_the_key() -> None:
    assert translate("en", "not_a_real_key") == "not_a_real_key"


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("UNDERSTAND", "Entendiendo"),
        ("RETRIEVE", "Recuperando esquema"),
        ("GENERATE", "Generando SQL"),
        ("VALIDATE", "Validando"),
        ("EXECUTE", "Ejecutando"),
        ("CHART", "Graficando"),
        ("NARRATE", "Redactando"),
    ],
)
def test_spanish_phase_labels(phase: str, expected: str) -> None:
    assert phase_label("es", phase) == expected


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("reason", CHART_REASONS)
def test_every_chart_reason_has_a_label(language: str, reason: str) -> None:
    key = f"chart_reason_{reason}"
    label = translate(language, key)

    assert label != key
    assert label != reason


def test_spanish_chart_card_shows_the_label_not_the_raw_reason() -> None:
    def t(key: str, **values: object) -> str:
        return translate("es", key, **values)

    rendered = render_template(
        "_chart.html",
        t=t,
        chart_data={
            "spec": {
                "kind": "bar",
                "x": "province",
                "y": ["n"],
                "title": "Provinces",
                "reason": "category_breakdown",
            },
            "columns": ["province", "n"],
            "rows": [["Pichincha", 3]],
        },
    )
    label = translate("es", "chart_reason_category_breakdown")
    why = translate("es", "chart_why")

    assert f"{why}: {label}" in rendered
    assert f"{why}: category_breakdown" not in rendered
    assert f"Provinces · {label}" in rendered
