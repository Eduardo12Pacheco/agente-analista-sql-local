"""Acceptance tests for benchmark v1 (T8/S23)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml
from sqlglot import exp, parse

from sqlagent.adapters.benchmark.yaml_repository import (
    DEFAULT_BENCHMARK_DIR,
    YamlBenchmarkRepository,
)
from sqlagent.adapters.semantic.fewshots_repository import load_fewshots
from sqlagent.bootstrap import build_semantic, build_warehouse
from sqlagent.config import Settings
from sqlagent.domain.retrieval import Bm25Retriever
from sqlagent.domain.semantic import SemanticLayer
from sqlagent.domain.sql_policy import SqlPolicy, ValidatedQuery

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_PATH = REPO_ROOT / "src/sqlagent/resources/benchmark/v1/questions.yaml"
MANIFEST_PATH = REPO_ROOT / "src/sqlagent/resources/warehouse/MANIFEST.json"

CATEGORY_QUOTAS = {
    "aggregation": 8,
    "filtering": 8,
    "join": 10,
    "grouping_topk": 10,
    "temporal": 7,
    "ratio_percentage": 6,
    "subquery_cte_window": 6,
    "entity_resolution": 5,
    "unanswerable_ambiguous": 6,
    "adversarial_safety": 6,
}
LANGUAGE_QUOTAS = {"es": 38, "en": 34}
DIFFICULTY_QUOTAS = {"easy": 24, "medium": 30, "hard": 18}
EXPECT_QUOTAS = {"answer": 60, "clarification": 3, "unanswerable": 3, "refusal": 6}


@pytest.fixture(scope="module")
def benchmark():
    return YamlBenchmarkRepository().load("v1")


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory: pytest.TempPathFactory):
    settings = Settings(data_dir=tmp_path_factory.mktemp("benchmark-warehouse"))
    instance = build_warehouse(settings)
    yield instance
    instance.close()


@pytest.fixture(scope="module")
def policy(warehouse) -> SqlPolicy:
    return SqlPolicy(catalog_tables=warehouse.catalog().table_names(), max_rows=1_000)


@pytest.fixture(scope="module")
def semantic() -> SemanticLayer:
    return build_semantic()


@pytest.fixture(scope="module")
def retriever(semantic) -> Bm25Retriever:
    return Bm25Retriever(semantic, load_fewshots())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _counts(items) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {
        "category": {},
        "language": {},
        "difficulty": {},
        "expect": {},
    }
    for item in items:
        for key, value in (
            ("category", item.category.value),
            ("language", item.lang.value),
            ("difficulty", item.difficulty.value),
            ("expect", item.expect.value),
        ):
            result[key][value] = result[key].get(value, 0) + 1
    return {key: dict(sorted(value.items())) for key, value in result.items()}


def _tables(sql: str) -> set[str]:
    tree = parse(sql, read="duckdb")[0]
    ctes = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}
    return {table.name for table in tree.find_all(exp.Table) if table.name not in ctes}


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split()).rstrip("; ")


def test_benchmark_has_exactly_72_sequential_items(benchmark) -> None:
    assert len(benchmark.items) == 72
    assert [item.id for item in benchmark.items] == [f"q{index:03d}" for index in range(1, 73)]
    assert len({item.id for item in benchmark.items}) == 72


def test_benchmark_composition_matches_d19(benchmark) -> None:
    counts = _counts(benchmark.items)

    assert counts["category"] == dict(sorted(CATEGORY_QUOTAS.items()))
    assert counts["language"] == dict(sorted(LANGUAGE_QUOTAS.items()))
    assert counts["difficulty"] == dict(sorted(DIFFICULTY_QUOTAS.items()))
    assert counts["expect"] == dict(sorted(EXPECT_QUOTAS.items()))
    assert len(benchmark.pairs()) == 12


def test_pairs_share_gold_sql_one_es_one_en(benchmark) -> None:
    pair_ids = [item.pair_id for item in benchmark.items if item.pair_id is not None]
    assert sorted(pair_ids) == sorted([f"p{index:02d}" for index in range(1, 13)] * 2)

    for pair_id, items in benchmark.pairs().items():
        assert len(items) == 2, pair_id
        assert {item.lang.value for item in items} == {"es", "en"}, pair_id
        assert len({item.gold_sql for item in items}) == 1, pair_id


def test_answerable_items_carry_gold_sql_and_others_do_not(benchmark) -> None:
    for item in benchmark.items:
        if item.expect.value == "answer":
            assert item.gold_sql, item.id
            assert item.category.value not in {"unanswerable_ambiguous", "adversarial_safety"}
        else:
            assert item.gold_sql is None, item.id
            assert item.category.value in {"unanswerable_ambiguous", "adversarial_safety"}


def test_every_gold_sql_passes_policy(benchmark, policy) -> None:
    for item in benchmark.items:
        if item.gold_sql is None:
            continue
        validated = policy.validate(item.gold_sql)
        assert isinstance(validated, ValidatedQuery)
        assert validated.limit_applied <= 1_000


def test_gold_sql_executes_deterministically_with_bounded_rows(
    benchmark, warehouse, policy
) -> None:
    for item in benchmark.items:
        if item.gold_sql is None:
            continue
        query = policy.validate(item.gold_sql)
        first = warehouse.execute(query)
        second = warehouse.execute(query)
        assert first.rows == second.rows, item.id
        assert first.columns == second.columns, item.id
        assert 1 <= len(first.rows) <= 200, (item.id, len(first.rows))


def test_ranked_questions_have_order_by(benchmark) -> None:
    for item in benchmark.items:
        if item.gold_sql is None or "ranking" not in item.tags:
            continue
        assert re.search(r"\bORDER\s+BY\b", item.gold_sql, re.IGNORECASE), item.id


def test_gold_sql_avoids_nondeterministic_functions(benchmark) -> None:
    forbidden = re.compile(r"\b(current_date|current_timestamp|now|random|uuid)\b", re.IGNORECASE)
    for item in benchmark.items:
        if item.gold_sql is not None:
            assert not forbidden.search(item.gold_sql), item.id


def test_no_gold_sql_uses_pseudonymised_literals(benchmark) -> None:
    for item in benchmark.items:
        if item.gold_sql is not None:
            assert "Persona natural" not in item.gold_sql, item.id
            assert not re.search(r"PN-\d{6}", item.gold_sql), item.id


def test_lock_file_matches_current_hashes_and_counts(benchmark) -> None:
    lock = json.loads((DEFAULT_BENCHMARK_DIR / "v1" / "benchmark.lock.json").read_text("utf-8"))

    assert lock["benchmark"] == "v1"
    assert lock["n"] == 72
    assert lock["questions_sha256"] == _sha256(QUESTIONS_PATH)
    assert lock["warehouse_manifest_sha256"] == _sha256(MANIFEST_PATH)
    assert lock["counts"]["category"] == dict(sorted(CATEGORY_QUOTAS.items()))
    assert lock["counts"]["language"] == dict(sorted(LANGUAGE_QUOTAS.items()))
    assert lock["counts"]["difficulty"] == dict(sorted(DIFFICULTY_QUOTAS.items()))
    assert lock["counts"]["expect"] == dict(sorted(EXPECT_QUOTAS.items()))
    assert lock["counts"]["pairs"] == 12


def test_fewshots_do_not_leak_into_benchmark(benchmark) -> None:
    fewshots = load_fewshots()
    leaked_questions = {_normalise(shot.question) for shot in fewshots}
    leaked_sql = {_normalise(shot.sql) for shot in fewshots}

    for item in benchmark.items:
        assert _normalise(item.question) not in leaked_questions, item.id
        if item.gold_sql is not None:
            assert _normalise(item.gold_sql) not in leaked_sql, item.id


def test_retrieval_table_recall_at_least_95_percent(benchmark, retriever) -> None:
    recalls: list[float] = []
    for item in benchmark.items:
        if item.gold_sql is None:
            continue
        expected = _tables(item.gold_sql)
        retrieved = set(retriever.search(item.question).tables)
        assert expected, item.id
        recalls.append(len(expected & retrieved) / len(expected))

    mean_recall = sum(recalls) / len(recalls)
    assert mean_recall >= 0.95, mean_recall


def test_questions_file_is_parsed_as_a_72_item_list() -> None:
    document = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, list)
    assert len(document) == 72
