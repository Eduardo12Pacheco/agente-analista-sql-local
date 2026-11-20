"""Unit tests for the benchmark v1 pydantic schema and YAML repository (T8/S23)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sqlagent.adapters.benchmark.yaml_repository import (
    DEFAULT_BENCHMARK_DIR,
    YamlBenchmarkRepository,
)
from sqlagent.application.evaluation.benchmark import (
    PAIR_COUNT,
    Benchmark,
    BenchmarkItem,
    Category,
    Difficulty,
    Expect,
    build_counts,
    build_lock,
)
from sqlagent.domain.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_PATH = REPO_ROOT / "src/sqlagent/resources/benchmark/v1/questions.yaml"
MANIFEST_PATH = REPO_ROOT / "src/sqlagent/resources/warehouse/MANIFEST.json"


def make_item(**overrides: object) -> BenchmarkItem:
    data: dict[str, object] = {
        "id": "q001",
        "category": "aggregation",
        "difficulty": "easy",
        "lang": "en",
        "question": "How many tenders are there?",
        "gold_sql": "SELECT COUNT(*) AS n FROM tenders",
        "pair_id": None,
        "expect": "answer",
        "tags": [],
        "notes": "",
    }
    data.update(overrides)
    return BenchmarkItem.model_validate(data)


def test_item_parses_gold_sql_for_answerable() -> None:
    item = make_item()

    assert item.category is Category.AGGREGATION
    assert item.difficulty is Difficulty.EASY
    assert item.expect is Expect.ANSWER
    assert item.pair_id is None


@pytest.mark.parametrize("bad_id", ["1", "q1", "q0001", "x001", ""])
def test_item_rejects_malformed_id(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        make_item(id=bad_id)


def test_answerable_item_requires_gold_sql() -> None:
    with pytest.raises(ValidationError, match="gold_sql"):
        make_item(gold_sql=None)


def test_non_answerable_item_forbids_gold_sql() -> None:
    with pytest.raises(ValidationError, match="gold_sql"):
        make_item(
            category="unanswerable_ambiguous",
            expect="unanswerable",
            gold_sql="SELECT COUNT(*) AS n FROM tenders",
        )


def test_category_and_expect_must_agree() -> None:
    with pytest.raises(ValidationError, match="expect"):
        make_item(category="adversarial_safety", expect="answer")
    with pytest.raises(ValidationError, match="expect"):
        make_item(category="unanswerable_ambiguous", expect="answer")


def test_question_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        make_item(question="   ")


def test_benchmark_requires_sequential_ids() -> None:
    with pytest.raises(ValidationError, match="sequential"):
        Benchmark(
            version="v1",
            items=(make_item(id="q002"), make_item(id="q001")),
        )


def test_benchmark_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="sequential"):
        Benchmark(version="v1", items=(make_item(), make_item()))


def test_pair_must_have_two_languages_and_one_sql() -> None:
    es = make_item(
        id="q001",
        lang="es",
        question="¿Cuántos procesos hay?",
        pair_id="p01",
    )
    en = make_item(id="q002", lang="en", pair_id="p01")
    benchmark = Benchmark(version="v1", items=(es, en))
    assert len(benchmark.pairs()) == 1

    with pytest.raises(ValidationError, match="pair"):
        Benchmark(version="v1", items=(es, make_item(id="q002", lang="es", pair_id="p01")))

    with pytest.raises(ValidationError, match="pair"):
        Benchmark(
            version="v1",
            items=(es, make_item(id="q002", pair_id="p01", gold_sql="SELECT 1 AS one")),
        )


def test_repository_loads_committed_benchmark() -> None:
    benchmark = YamlBenchmarkRepository().load("v1")

    assert benchmark.version == "v1"
    assert len(benchmark.items) == 72
    assert benchmark.items[0].id == "q001"
    assert benchmark.items[-1].id == "q072"
    counts = build_counts(benchmark)
    assert counts.pairs == PAIR_COUNT
    assert counts.language == {"es": 38, "en": 34}


def test_repository_missing_file_raises_config_error(tmp_path: Path) -> None:
    repository = YamlBenchmarkRepository(tmp_path)

    with pytest.raises(ConfigError, match=r"questions\.yaml"):
        repository.load("v1")


def test_repository_rejects_malformed_yaml(tmp_path: Path) -> None:
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "questions.yaml").write_text("items: [\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="parse"):
        YamlBenchmarkRepository(tmp_path).load("v1")


def test_repository_rejects_non_list_document(tmp_path: Path) -> None:
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "questions.yaml").write_text("schema: v1\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="list"):
        YamlBenchmarkRepository(tmp_path).load("v1")
