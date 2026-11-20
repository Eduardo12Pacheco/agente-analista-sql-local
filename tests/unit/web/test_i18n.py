"""Bilingual UI dictionaries must stay in lockstep (S29/T10)."""

from __future__ import annotations

import pytest

from sqlagent.adapters.web.i18n import LANGUAGES, catalog, phase_label, translate

pytestmark = pytest.mark.unit


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
