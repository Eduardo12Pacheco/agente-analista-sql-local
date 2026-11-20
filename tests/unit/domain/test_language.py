"""Language detection for Spanish and English analytics questions."""

from __future__ import annotations

import pytest

from sqlagent.domain.language import EN_STOPWORDS, ES_STOPWORDS, detect_language
from sqlagent.domain.models import Language

pytestmark = pytest.mark.unit
MIN_STOPWORDS = 40

CASES = [
    ("¿Cuántos procesos hay?", Language.ES),
    ("¿Cuántos procesos de contratación hay?", Language.ES),
    ("Cuantos contratos existen", Language.ES),
    ("¿Cuál es el monto total adjudicado en dólares?", Language.ES),
    ("Muéstrame los proveedores de Guayas", Language.ES),
    ("How many tenders are there?", Language.EN),
    ("Top 10 suppliers by total awarded amount", Language.EN),
    ("What percentage of tenders were competitive?", Language.EN),
    ("Show me the buyers from Pichincha", Language.EN),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_detect_language(text: str, expected: Language) -> None:
    assert detect_language(text) is expected


def test_stopword_sets_have_at_least_forty_entries() -> None:
    assert len(ES_STOPWORDS) >= MIN_STOPWORDS
    assert len(EN_STOPWORDS) >= MIN_STOPWORDS


def test_accented_text_wins_a_tie() -> None:
    assert detect_language("procesos ñ") is Language.ES
    assert detect_language("procesos") is Language.EN


def test_empty_and_numeric_text_default_to_english() -> None:
    assert detect_language("") is Language.EN
    assert detect_language("12345 67890") is Language.EN


def test_uppercase_and_punctuation_are_ignored_for_scoring() -> None:
    assert detect_language("¿CUÁNTOS PROCESOS HAY?") is Language.ES
    assert detect_language("HOW MANY TENDERS ARE THERE?") is Language.EN


def test_language_enum_is_string_compatible() -> None:
    assert Language.ES == "es"
    assert Language.EN == "en"
