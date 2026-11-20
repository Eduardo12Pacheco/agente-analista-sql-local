"""Benchmark schema, composition rules and lock (S23/D19).

Benchmark v1 is a versioned, hand-curated evaluation set.  The YAML document is
a top-level list of items; pydantic validates every field and refuses partial or
inconsistent documents, so a load error is always a ``ConfigError`` surfaced by
the repository adapter.  The lock file pins the exact bytes of ``questions.yaml``
and of the warehouse manifest so a benchmark or data change cannot silently
invalidate recorded model outputs.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sqlagent.domain.models import Language

BENCHMARK_VERSION = "v1"


class Category(StrEnum):
    """D19 categories; the last two are the non-answerable groups."""

    AGGREGATION = "aggregation"
    FILTERING = "filtering"
    JOIN = "join"
    GROUPING_TOPK = "grouping_topk"
    TEMPORAL = "temporal"
    RATIO_PERCENTAGE = "ratio_percentage"
    SUBQUERY_CTE_WINDOW = "subquery_cte_window"
    ENTITY_RESOLUTION = "entity_resolution"
    UNANSWERABLE_AMBIGUOUS = "unanswerable_ambiguous"
    ADVERSARIAL_SAFETY = "adversarial_safety"


class Difficulty(StrEnum):
    """Question difficulty (D19)."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Expect(StrEnum):
    """Expected agent behaviour used by the execution-accuracy scorer (D19)."""

    ANSWER = "answer"
    CLARIFICATION = "clarification"
    UNANSWERABLE = "unanswerable"
    REFUSAL = "refusal"


ANSWERABLE_CATEGORIES: frozenset[Category] = frozenset(
    {
        Category.AGGREGATION,
        Category.FILTERING,
        Category.JOIN,
        Category.GROUPING_TOPK,
        Category.TEMPORAL,
        Category.RATIO_PERCENTAGE,
        Category.SUBQUERY_CTE_WINDOW,
        Category.ENTITY_RESOLUTION,
    }
)

CATEGORY_QUOTAS: dict[Category, int] = {
    Category.AGGREGATION: 8,
    Category.FILTERING: 8,
    Category.JOIN: 10,
    Category.GROUPING_TOPK: 10,
    Category.TEMPORAL: 7,
    Category.RATIO_PERCENTAGE: 6,
    Category.SUBQUERY_CTE_WINDOW: 6,
    Category.ENTITY_RESOLUTION: 5,
    Category.UNANSWERABLE_AMBIGUOUS: 6,
    Category.ADVERSARIAL_SAFETY: 6,
}

# D19's 24/30/18 difficulty split sums to 72, so it is applied to the complete
# benchmark (answerable + non-answerable items), which is the only self-consistent
# reading of the specification.
DIFFICULTY_QUOTAS: dict[Difficulty, int] = {
    Difficulty.EASY: 24,
    Difficulty.MEDIUM: 30,
    Difficulty.HARD: 18,
}

LANGUAGE_QUOTAS: dict[Language, int] = {
    Language.ES: 38,
    Language.EN: 34,
}

EXPECT_QUOTAS: dict[Expect, int] = {
    Expect.ANSWER: 60,
    Expect.CLARIFICATION: 3,
    Expect.UNANSWERABLE: 3,
    Expect.REFUSAL: 6,
}

PAIR_COUNT = 12
PAIR_SIZE = 2
BENCHMARK_SIZE = 72


class BenchmarkItem(BaseModel):
    """One benchmark question with its gold SQL and expectations (S23)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^q\d{3}$")
    category: Category
    difficulty: Difficulty
    lang: Language
    question: str = Field(min_length=1)
    gold_sql: str | None = None
    pair_id: str | None = Field(default=None, pattern=r"^p\d{2}$")
    expect: Expect
    tags: tuple[str, ...] = ()
    notes: str = ""

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()

    @field_validator("gold_sql")
    @classmethod
    def _gold_sql_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("gold_sql must be null or a non-empty string")
        return value.strip() if value is not None else None

    @field_validator("tags")
    @classmethod
    def _tags_normalised(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(tag.strip() for tag in value if tag.strip())
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("tags must be unique")
        return cleaned

    @model_validator(mode="after")
    def _consistent_expectations(self) -> BenchmarkItem:
        if self.category in ANSWERABLE_CATEGORIES:
            if self.expect is not Expect.ANSWER:
                raise ValueError(
                    f"{self.id}: answerable category "
                    f"{self.category.value!r} must use expect='answer'"
                )
            if self.gold_sql is None:
                raise ValueError(f"{self.id}: expect='answer' requires gold_sql")
        elif self.category is Category.UNANSWERABLE_AMBIGUOUS:
            if self.expect not in {Expect.CLARIFICATION, Expect.UNANSWERABLE}:
                raise ValueError(
                    f"{self.id}: unanswerable_ambiguous must use "
                    "expect='clarification' or expect='unanswerable'"
                )
            if self.gold_sql is not None:
                raise ValueError(f"{self.id}: non-answerable items must not carry gold_sql")
        else:  # adversarial_safety
            if self.expect is not Expect.REFUSAL:
                raise ValueError(f"{self.id}: adversarial_safety must use expect='refusal'")
            if self.gold_sql is not None:
                raise ValueError(f"{self.id}: non-answerable items must not carry gold_sql")
        if self.pair_id is not None and self.expect is not Expect.ANSWER:
            raise ValueError(f"{self.id}: only answerable items may belong to a pair")
        return self


class Benchmark(BaseModel):
    """A validated benchmark version with sequential ids and coherent pairs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    items: tuple[BenchmarkItem, ...]

    @model_validator(mode="after")
    def _sequential_ids(self) -> Benchmark:
        ids = [item.id for item in self.items]
        expected = [f"q{index:03d}" for index in range(1, len(ids) + 1)]
        if ids != expected:
            raise ValueError(f"items must have sequential ids q001..q{len(ids):03d}")
        return self

    @model_validator(mode="after")
    def _coherent_pairs(self) -> Benchmark:
        pairs: dict[str, list[BenchmarkItem]] = {}
        for item in self.items:
            if item.pair_id is not None:
                pairs.setdefault(item.pair_id, []).append(item)
        for pair_id, members in pairs.items():
            if len(members) != PAIR_SIZE:
                raise ValueError(f"pair {pair_id} must contain exactly two items")
            if {member.lang for member in members} != {Language.ES, Language.EN}:
                raise ValueError(f"pair {pair_id} must contain one es and one en item")
            if len({member.gold_sql for member in members}) != 1:
                raise ValueError(f"pair {pair_id} items must share identical gold_sql")
        return self

    def pairs(self) -> dict[str, tuple[BenchmarkItem, ...]]:
        """Return pair id -> both items, in file order."""

        grouped: dict[str, list[BenchmarkItem]] = {}
        for item in self.items:
            if item.pair_id is not None:
                grouped.setdefault(item.pair_id, []).append(item)
        return {pair_id: tuple(items) for pair_id, items in grouped.items()}


class LockCounts(BaseModel):
    """Composition counts pinned by ``benchmark.lock.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: dict[str, int]
    language: dict[str, int]
    difficulty: dict[str, int]
    expect: dict[str, int]
    pairs: int


class BenchmarkLock(BaseModel):
    """Hash and count lock for one benchmark version (S23/D18)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark: str
    questions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    warehouse_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    n: int
    counts: LockCounts


def _counted(values: list[str], keys: tuple[str, ...]) -> dict[str, int]:
    counter = Counter(values)
    return {key: counter[key] for key in keys}


def build_counts(benchmark: Benchmark) -> LockCounts:
    """Compute the deterministic composition counts of a benchmark."""

    items = benchmark.items
    return LockCounts(
        category=_counted(
            [item.category.value for item in items],
            tuple(category.value for category in Category),
        ),
        language=_counted(
            [item.lang.value for item in items],
            tuple(language.value for language in Language),
        ),
        difficulty=_counted(
            [item.difficulty.value for item in items],
            tuple(difficulty.value for difficulty in Difficulty),
        ),
        expect=_counted(
            [item.expect.value for item in items],
            tuple(expect.value for expect in Expect),
        ),
        pairs=len(benchmark.pairs()),
    )


def build_lock(benchmark: Benchmark, questions_path: Path, manifest_path: Path) -> BenchmarkLock:
    """Build the lock for the exact bytes on disk."""

    return BenchmarkLock(
        benchmark=benchmark.version,
        questions_sha256=hashlib.sha256(questions_path.read_bytes()).hexdigest(),
        warehouse_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        n=len(benchmark.items),
        counts=build_counts(benchmark),
    )


__all__ = [
    "ANSWERABLE_CATEGORIES",
    "BENCHMARK_SIZE",
    "BENCHMARK_VERSION",
    "CATEGORY_QUOTAS",
    "DIFFICULTY_QUOTAS",
    "EXPECT_QUOTAS",
    "LANGUAGE_QUOTAS",
    "PAIR_COUNT",
    "PAIR_SIZE",
    "Benchmark",
    "BenchmarkItem",
    "BenchmarkLock",
    "Category",
    "Difficulty",
    "Expect",
    "LockCounts",
    "build_counts",
    "build_lock",
]
