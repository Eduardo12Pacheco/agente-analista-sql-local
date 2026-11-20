"""Table-driven tests for the SQL AST guardrail (T3, S16/D14)."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import pytest
import sqlglot
import yaml
from sqlglot import exp

from sqlagent.domain import errors, sql_policy
from sqlagent.domain.errors import GuardrailCode, GuardrailViolation
from sqlagent.domain.sql_policy import (
    ALLOWED_FUNCTIONS,
    ALLOWED_NODE_TYPES,
    CATALOG_DEFAULT,
    WRITE_INTENT_CODES,
    SqlPolicy,
    ValidatedQuery,
)

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
CATALOG = frozenset({"buyers", "suppliers", "tenders", "awards", "contracts", "tender_items"})
CAP = 1000
CUSTOM_CAP = 25
SMALL_LIMIT = 10
PERF_BOUND_S = 0.1


def _load(name: str) -> list[dict[str, Any]]:
    data = yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _legit_queries() -> list[str]:
    data = _load("legit_sql.yaml")
    assert all(isinstance(item, str) for item in data)
    return list(data)


def _adversarial_cases() -> list[tuple[str, GuardrailCode]]:
    cases = [
        (item["sql"], GuardrailCode(item["expected_code"]))
        for item in _load("adversarial_sql.yaml")
    ]
    cases.extend(
        [
            ("SELECT 1" + "+1" * 1000, GuardrailCode.TOO_COMPLEX),
            ("SELECT read_text('/etc/passwd')", GuardrailCode.FORBIDDEN_FUNCTION),
            ("SELECT " + "x" * 4001, GuardrailCode.TOO_LONG),
        ]
    )
    return cases


def _top_level_limit(sql: str) -> int | None:
    parsed = sqlglot.parse(sql, read="duckdb")
    assert len(parsed) == 1
    root = parsed[0]
    assert root is not None
    limit = root.args.get("limit")
    if limit is None:
        return None
    expression = limit.expression
    assert isinstance(expression, exp.Literal)
    return int(expression.this)


@pytest.mark.parametrize(("sql", "code"), _adversarial_cases(), ids=lambda value: None)
def test_adversarial_sql_is_rejected_with_the_expected_code(sql: str, code: GuardrailCode) -> None:
    policy = SqlPolicy(CATALOG)

    with pytest.raises(GuardrailViolation) as excinfo:
        policy.validate(sql)

    assert excinfo.value.code is code, str(excinfo.value)


@pytest.mark.parametrize("sql", _legit_queries(), ids=lambda value: None)
def test_legitimate_sql_is_accepted_and_bounded(sql: str) -> None:
    policy = SqlPolicy(CATALOG)

    validated = policy.validate(sql)

    assert isinstance(validated, ValidatedQuery)
    assert validated.original_sql == sql
    assert validated.limit_applied <= CAP
    assert _top_level_limit(validated.sql) is not None
    assert _top_level_limit(validated.sql) <= CAP
    reparsed = sqlglot.parse(validated.sql, read="duckdb")
    assert len(reparsed) == 1
    assert validated.sql == sqlglot.parse_one(validated.sql, read="duckdb").sql(
        dialect="duckdb", comments=False
    )


def test_limit_is_injected_when_missing() -> None:
    validated = SqlPolicy(CATALOG).validate("SELECT * FROM tenders")

    assert _top_level_limit(validated.sql) == CAP
    assert validated.limit_applied == CAP


def test_larger_limit_is_clamped() -> None:
    validated = SqlPolicy(CATALOG).validate("SELECT * FROM tenders LIMIT 5000")

    assert _top_level_limit(validated.sql) == CAP
    assert validated.limit_applied == CAP


def test_limit_is_customisable_and_small_limits_survive() -> None:
    policy = SqlPolicy(CATALOG, max_rows=CUSTOM_CAP)

    injected = policy.validate("SELECT * FROM tenders")
    small = policy.validate("SELECT * FROM tenders LIMIT 10")

    assert _top_level_limit(injected.sql) == CUSTOM_CAP
    assert _top_level_limit(small.sql) == SMALL_LIMIT
    assert small.limit_applied == SMALL_LIMIT


def test_non_literal_limit_is_replaced_by_the_cap() -> None:
    validated = SqlPolicy(CATALOG).validate("SELECT * FROM tenders LIMIT 1 + 1")

    assert _top_level_limit(validated.sql) == CAP


def test_limit_is_added_to_set_operations() -> None:
    validated = SqlPolicy(CATALOG).validate(
        "SELECT buyer_id FROM tenders UNION ALL SELECT buyer_id FROM buyers"
    )

    assert _top_level_limit(validated.sql) == CAP
    assert validated.tables == ("buyers", "tenders")


def test_comments_are_dropped_from_the_regenerated_sql() -> None:
    validated = SqlPolicy(CATALOG).validate("/* hi */ SELECT * FROM tenders -- bye")

    assert "/*" not in validated.sql
    assert "--" not in validated.sql


def test_tables_are_extracted_case_insensitively_and_schema_qualified() -> None:
    validated = SqlPolicy(CATALOG).validate(
        "SELECT * FROM MAIN.Tenders t JOIN Buyers b ON b.buyer_id = t.buyer_id"
    )

    assert validated.tables == ("buyers", "tenders")


def test_cte_names_are_not_reported_as_tables() -> None:
    validated = SqlPolicy(CATALOG).validate(
        "WITH spend AS (SELECT * FROM awards) SELECT * FROM spend"
    )

    assert validated.tables == ("awards",)


def test_validated_query_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError):
        ValidatedQuery(  # type: ignore[call-arg]
            sql="SELECT 1",
            tables=(),
            original_sql="SELECT 1",
            limit_applied=1000,
        )


def test_write_intent_codes_cover_the_refusal_categories() -> None:
    assert set(GuardrailCode) >= WRITE_INTENT_CODES
    assert {
        GuardrailCode.NOT_SELECT,
        GuardrailCode.FORBIDDEN_NODE,
        GuardrailCode.TABLE_FUNCTION,
    } == set(WRITE_INTENT_CODES)


def test_default_catalog_matches_the_bundled_warehouse() -> None:
    assert CATALOG_DEFAULT == CATALOG


def test_guardrail_code_is_re_exported_from_the_policy_module() -> None:
    assert sql_policy.GuardrailCode is errors.GuardrailCode


def test_allowed_functions_cover_the_documented_analytic_set() -> None:
    assert {
        "count",
        "sum",
        "avg",
        "median",
        "date_trunc",
        "row_number",
        "string_agg",
        "list",
        "regexp_matches",
    } <= ALLOWED_FUNCTIONS
    assert "read_csv" not in ALLOWED_FUNCTIONS
    assert "current_date" not in ALLOWED_FUNCTIONS


def test_policy_performance_stays_under_the_documented_budget() -> None:
    policy = SqlPolicy(CATALOG)
    timings: list[float] = []
    for sql in _legit_queries():
        start = time.perf_counter()
        policy.validate(sql)
        timings.append(time.perf_counter() - start)

    timings.sort()
    p95 = timings[math.ceil(0.95 * len(timings)) - 1]

    assert p95 < PERF_BOUND_S  # generous; the real budget is 20 ms (S40)


def test_pinned_sqlglot_behaviour_used_by_the_policy() -> None:
    """Loudly fail when a sqlglot upgrade changes the AST shapes the policy relies on."""

    assert sqlglot.__version__.startswith("30.")

    with_query = sqlglot.parse_one("WITH x AS (SELECT 1) SELECT * FROM x", read="duckdb")
    assert isinstance(with_query, exp.Select)
    assert isinstance(with_query.find(exp.With), exp.With)

    union = sqlglot.parse_one("SELECT 1 UNION SELECT 2", read="duckdb")
    assert isinstance(union, exp.Union)

    read_csv = sqlglot.parse_one("SELECT * FROM read_csv('/etc/passwd')", read="duckdb")
    assert isinstance(read_csv, exp.Select)
    table = read_csv.find(exp.Table)
    assert table is not None
    assert isinstance(table.this, exp.ReadCSV)

    assert isinstance(
        sqlglot.parse_one("SELECT date_trunc('month', x)", read="duckdb").find(exp.TimestampTrunc),
        exp.TimestampTrunc,
    )
    assert isinstance(
        sqlglot.parse_one("SELECT list(x)", read="duckdb").find(exp.ArrayAgg),
        exp.ArrayAgg,
    )
    assert exp.Count in ALLOWED_NODE_TYPES
    assert exp.Anonymous in ALLOWED_NODE_TYPES
