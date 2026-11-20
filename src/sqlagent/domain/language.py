"""Deterministic, dependency-free Spanish/English language detection.

The detector is intentionally lexical: the benchmark has only two languages and
questions are short.  Scoring is ``#ES stopwords + 2 * accented marker`` versus
``#EN stopwords``; ties fall back to Spanish when the text carries a Spanish
marker, otherwise English (D5/S12).
"""

from __future__ import annotations

import re
import unicodedata

from sqlagent.domain.models import Language

# Common function words, deliberately excluding words shared by both languages
# ("a", "no", "me", "he") so they cannot skew the score.
ES_STOPWORDS = frozenset(
    {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "de",
        "del",
        "al",
        "y",
        "o",
        "que",
        "en",
        "por",
        "para",
        "con",
        "sin",
        "sobre",
        "entre",
        "como",
        "cual",
        "cuales",
        "cuanto",
        "cuanta",
        "cuantos",
        "cuantas",
        "quien",
        "quienes",
        "donde",
        "cuando",
        "hay",
        "es",
        "son",
        "esta",
        "estan",
        "fue",
        "fueron",
        "ser",
        "tiene",
        "tienen",
        "se",
        "su",
        "sus",
        "mi",
        "mis",
        "tu",
        "tus",
        "nuestro",
        "nuestra",
        "este",
        "estos",
        "estas",
        "ese",
        "esa",
        "esos",
        "esas",
        "mas",
        "menos",
        "muy",
        "tambien",
        "pero",
        "si",
        "ya",
        "solo",
        "todo",
        "toda",
        "todos",
        "todas",
        "otro",
        "otra",
        "desde",
        "hasta",
        "cada",
        "tanto",
        "poco",
        "mucho",
        "varios",
        "algunas",
        "algunos",
        "muestrame",
        "muestranos",
        "dame",
        "lista",
        "listar",
    }
)

EN_STOPWORDS = frozenset(
    {
        "the",
        "an",
        "and",
        "or",
        "but",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "without",
        "about",
        "between",
        "into",
        "over",
        "under",
        "from",
        "by",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "can",
        "could",
        "should",
        "may",
        "might",
        "must",
        "this",
        "that",
        "these",
        "those",
        "i",
        "you",
        "we",
        "they",
        "it",
        "my",
        "your",
        "our",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "how",
        "many",
        "much",
        "more",
        "most",
        "less",
        "least",
        "all",
        "any",
        "some",
        "each",
        "every",
        "both",
        "either",
        "neither",
        "not",
        "than",
        "then",
        "there",
        "here",
        "such",
        "own",
        "same",
        "so",
        "too",
        "very",
        "just",
        "also",
        "only",
        "show",
        "list",
        "please",
    }
)

_SPANISH_MARKERS = frozenset("¿¡ñáéíóúü")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_COMBINING_MARKS = frozenset(chr(codepoint) for codepoint in range(0x0300, 0x0370))


def _accent_fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if char not in _COMBINING_MARKS)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(_accent_fold(text))


def detect_language(text: str) -> Language:
    """Return the dominant language of ``text`` without ever raising."""

    lowered = text.casefold()
    es_score = sum(1 for token in _tokens(text) if token in ES_STOPWORDS)
    en_score = sum(1 for token in _tokens(text) if token in EN_STOPWORDS)
    has_spanish_marker = any(char in _SPANISH_MARKERS for char in lowered)
    if has_spanish_marker:
        es_score += 2

    if es_score > en_score:
        return Language.ES
    if en_score > es_score:
        return Language.EN
    return Language.ES if has_spanish_marker else Language.EN
