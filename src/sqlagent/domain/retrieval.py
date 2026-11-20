"""Deterministic BM25 retrieval over the bilingual semantic layer (S7/D13).

The retriever is pure domain code: it indexes the documented tables, columns,
metrics, glossary entries and few-shots, ranks them with BM25, and returns the
selected tables (with the shortest foreign-key bridges), their metrics and the
best few-shots.  Every ordering is deterministic so prompts and cassettes are
stable.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlagent.domain.models import Language
from sqlagent.domain.semantic import Metric, SemanticLayer

BM25_K1 = 1.2
BM25_B = 0.75
DEFAULT_TOP_DOCS = 8
DEFAULT_TOP_FEWSHOTS = 3
MAX_TABLES = 4
FALLBACK_TABLES: tuple[str, ...] = ("tenders", "awards")

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_EN_STOPWORDS = _words(
    """a about above after again all also am an and any are as at be been before
    being below between both but by can could did do does doing down during each
    few for from further had has have having he her here hers him his how i if in
    into is it its itself just many may me more most much must my no nor not now
    of off on once only or other our out over own per same she should so some such
    than that the their them then there these they this those through to too top
    under until up very was we were what when where which while who whom why will
    with would you your"""
)

_ES_STOPWORDS = _words(
    """a al algo algun alguna algunas alguno algunos ante antes como con contra cual
    cuales cualquier cuando cuanto cuanta cuantos cuantas de del desde donde dos el
    ella ellas ellos en entre era eran es esa esas ese eso esos esta estas este esto
    estos fue fueron ha han hasta hay la las le les lo los mas me mi mis mucho muchos
    muy no nos o os otra otras otro otros para pero poco por porque que quien quienes
    se ser si sin sobre son su sus tambien te tiene tienen todo toda todas todos un
    una unas uno unos y ya"""
)

_STOPWORDS = _EN_STOPWORDS | _ES_STOPWORDS


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return decomposed.encode("ascii", "ignore").decode("ascii")


_MIN_STEM_LENGTH = 4


def _stem(token: str) -> str:
    """Light Spanish/English plural stemming (D13)."""

    if len(token) <= _MIN_STEM_LENGTH:
        return token
    if token.endswith("es"):
        return token[:-2]
    if token.endswith("s"):
        return token[:-1]
    return token


def tokenize(text: str) -> tuple[str, ...]:
    """Lowercase, accent-fold, split, drop stopwords and lightly stem."""

    return tuple(
        _stem(match) for match in _TOKEN_RE.findall(_fold(text)) if match not in _STOPWORDS
    )


class DocKind(StrEnum):
    """Kind of indexed semantic document."""

    TABLE = "table"
    COLUMN = "column"
    METRIC = "metric"
    GLOSSARY = "glossary"
    FEWSHOT = "fewshot"


@dataclass(frozen=True, slots=True)
class FewShot:
    """One question/SQL example returned by retrieval (T7 loads them)."""

    question: str
    sql: str
    language: Language
    tables: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievedDoc:
    """An indexed document with its BM25 score for the current question."""

    kind: DocKind
    name: str
    text: str
    tables: tuple[str, ...] = ()
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Everything GENERATE needs from the semantic layer (D13)."""

    tables: tuple[str, ...]
    metrics: tuple[Metric, ...]
    fewshots: tuple[FewShot, ...]
    docs: tuple[RetrievedDoc, ...]

    def render_context(self, semantic: SemanticLayer) -> str:
        """Render a deterministic, prompt-ready schema context (D13)."""

        lines: list[str] = []
        for name in self.tables:
            table = semantic.table(name)
            if table is None:  # pragma: no cover - retriever only selects known tables
                continue
            lines.append(f"TABLE {table.name}: {table.description_en} | {table.description_es}")
            for column in table.columns:
                lookupable = " [lookupable]" if column.lookupable else ""
                lines.append(
                    f"  {column.name} {column.type}: {column.description_en} | "
                    f"{column.description_es}{lookupable}"
                )
        if self.metrics:
            lines.append("METRICS:")
            for metric in self.metrics:
                lines.append(
                    f"  {metric.name} = {metric.expression_sql}: "
                    f"{metric.description_en} | {metric.description_es}"
                )
        if self.fewshots:
            lines.append("EXAMPLES:")
            for fewshot in self.fewshots:
                lines.append(f"  Q: {fewshot.question}")
                lines.append(f"  SQL: {fewshot.sql}")
        return "\n".join(lines)


class Bm25Retriever:
    """BM25 index over the semantic layer, with FK bridging and few-shots."""

    def __init__(self, semantic: SemanticLayer, fewshots: Sequence[FewShot] = ()) -> None:
        self.semantic = semantic
        self.fewshots = tuple(fewshots)
        self._docs = self._build_documents()
        self._tokens = tuple(tokenize(doc.text) for doc in self._docs)
        self._lengths = tuple(len(tokens) for tokens in self._tokens)
        self._average_length = sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        self._document_frequency = self._compute_document_frequency()
        self._adjacency = self._build_adjacency()

    # -- index ---------------------------------------------------------
    def _build_documents(self) -> tuple[RetrievedDoc, ...]:
        docs: list[RetrievedDoc] = []
        for table in self.semantic.tables:
            docs.append(
                RetrievedDoc(
                    kind=DocKind.TABLE,
                    name=table.name,
                    text=" ".join(
                        (
                            table.name,
                            table.description_en,
                            table.description_es,
                            *table.synonyms,
                        )
                    ),
                    tables=(table.name,),
                )
            )
            for column in table.columns:
                docs.append(
                    RetrievedDoc(
                        kind=DocKind.COLUMN,
                        name=f"{table.name}.{column.name}",
                        text=" ".join(
                            (
                                f"{table.name}.{column.name}",
                                column.name,
                                column.description_en,
                                column.description_es,
                                *column.synonyms,
                                *column.samples,
                            )
                        ),
                        tables=(table.name,),
                    )
                )
        for metric in self.semantic.metrics:
            docs.append(
                RetrievedDoc(
                    kind=DocKind.METRIC,
                    name=metric.name,
                    text=" ".join(
                        (
                            metric.name,
                            metric.description_en,
                            metric.description_es,
                            *metric.synonyms,
                        )
                    ),
                    tables=metric.tables,
                )
            )
        for entry in self.semantic.glossary:
            docs.append(
                RetrievedDoc(
                    kind=DocKind.GLOSSARY,
                    name=entry.terms[0],
                    text=" ".join((*entry.terms, entry.meaning)),
                )
            )
        for fewshot in self.fewshots:
            docs.append(
                RetrievedDoc(
                    kind=DocKind.FEWSHOT,
                    name=fewshot.question,
                    text=f"{fewshot.question} {fewshot.language.value}",
                    tables=fewshot.tables,
                )
            )
        return tuple(docs)

    def _compute_document_frequency(self) -> dict[str, int]:
        frequencies: Counter[str] = Counter()
        for tokens in self._tokens:
            frequencies.update(set(tokens))
        return dict(frequencies)

    def _build_adjacency(self) -> dict[str, tuple[str, ...]]:
        neighbours: dict[str, list[str]] = {}
        for relationship in self.semantic.relationships:
            source = relationship.from_.partition(".")[0]
            target = relationship.to.partition(".")[0]
            if not source or not target:
                continue
            for left, right in ((source, target), (target, source)):
                bucket = neighbours.setdefault(left, [])
                if right not in bucket:
                    bucket.append(right)
        return {table: tuple(items) for table, items in neighbours.items()}

    # -- ranking -------------------------------------------------------
    def _score(self, query_tokens: Sequence[str]) -> list[float]:
        total_docs = len(self._docs)
        average_length = self._average_length or 1.0
        scores: list[float] = []
        for index, tokens in enumerate(self._tokens):
            counts = Counter(tokens)
            length = self._lengths[index]
            score = 0.0
            for token in query_tokens:
                frequency = counts.get(token, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequency.get(token, 0)
                idf = math.log(
                    1.0 + (total_docs - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + BM25_K1 * (
                    1.0 - BM25_B + BM25_B * (length / average_length)
                )
                score += idf * (frequency * (BM25_K1 + 1.0)) / denominator
            scores.append(score)
        return scores

    def _fallback_tables(self) -> tuple[str, ...]:
        available = tuple(table.name for table in self.semantic.tables)
        fallback = tuple(name for name in FALLBACK_TABLES if name in available)
        if fallback:
            return fallback
        return available[:2]

    def _shortest_path(self, start: str, goal: str) -> tuple[str, ...]:
        if start == goal:
            return (start,)
        queue: list[tuple[str, ...]] = [(start,)]
        visited = {start}
        while queue:
            path = queue.pop(0)
            for neighbour in self._adjacency.get(path[-1], ()):
                if neighbour in visited:
                    continue
                candidate = (*path, neighbour)
                if neighbour == goal:
                    return candidate
                visited.add(neighbour)
                queue.append(candidate)
        return ()

    def _select_tables(self, ranked: Sequence[RetrievedDoc]) -> tuple[str, ...]:
        # Direct schema mentions (table/column/few-shot docs) outrank tables that
        # are merely referenced by a metric: a metric can match many query words
        # without being the table the question is actually about.
        direct: dict[str, float] = {}
        referenced: dict[str, float] = {}
        for doc in ranked:
            bucket = referenced if doc.kind is DocKind.METRIC else direct
            for table in doc.tables:
                bucket[table] = max(bucket.get(table, 0.0), doc.score)
        if not direct and not referenced:
            return self._fallback_tables()

        ordered = sorted(direct, key=direct.__getitem__, reverse=True)
        for table in sorted(referenced, key=referenced.__getitem__, reverse=True):
            if table not in ordered:
                ordered.append(table)

        # Reserve room for join bridges before filling with lower-ranked direct
        # tables: a bridge is what makes the top tables usable in one query.
        selected = list(ordered[:2])
        for index, source in enumerate(ordered):
            for target in ordered[index + 1 :]:
                for bridge in self._shortest_path(source, target):
                    if bridge not in selected and bridge not in ordered[:2]:
                        selected.append(bridge)
        for table in ordered[2:]:
            if table not in selected:
                selected.append(table)
        return tuple(selected[:MAX_TABLES]) or self._fallback_tables()

    def _metrics_for(self, tables: Sequence[str]) -> tuple[Metric, ...]:
        selected = set(tables)
        return tuple(metric for metric in self.semantic.metrics if set(metric.tables) <= selected)

    def _fewshots_for(self, ranked: Sequence[RetrievedDoc]) -> tuple[FewShot, ...]:
        positions = {fewshot.question: index for index, fewshot in enumerate(self.fewshots)}
        selected = [
            self.fewshots[positions[doc.name]]
            for doc in ranked
            if doc.kind is DocKind.FEWSHOT and doc.name in positions
        ]
        if not selected:
            selected = list(self.fewshots)
        return tuple(selected[:DEFAULT_TOP_FEWSHOTS])

    def search(self, question: str, k: int = DEFAULT_TOP_DOCS) -> RetrievalResult:
        """Retrieve tables, metrics, few-shots and top documents for a question."""

        query_tokens = tokenize(question)
        limit = max(1, k)
        if not query_tokens:
            tables = self._fallback_tables()
            return RetrievalResult(
                tables=tables,
                metrics=self._metrics_for(tables),
                fewshots=self._fewshots_for(()),
                docs=(),
            )

        scores = self._score(query_tokens)
        ranked = tuple(
            RetrievedDoc(
                kind=doc.kind,
                name=doc.name,
                text=doc.text,
                tables=doc.tables,
                score=scores[index],
            )
            for index, doc in enumerate(self._docs)
        )
        positive = tuple(
            doc for doc in sorted(ranked, key=lambda doc: doc.score, reverse=True) if doc.score > 0
        )
        top = positive[:limit]
        tables = self._select_tables(positive)
        return RetrievalResult(
            tables=tables,
            metrics=self._metrics_for(tables),
            fewshots=self._fewshots_for(positive),
            docs=top,
        )


__all__ = [
    "DEFAULT_TOP_DOCS",
    "DEFAULT_TOP_FEWSHOTS",
    "MAX_TABLES",
    "Bm25Retriever",
    "DocKind",
    "FewShot",
    "RetrievalResult",
    "RetrievedDoc",
    "tokenize",
]
