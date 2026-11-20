"""Hypothesis properties for the SQL guardrail (T3, S16/D14)."""

from __future__ import annotations

import pytest
import sqlglot
from hypothesis import given
from hypothesis import strategies as st

from sqlagent.domain.errors import GuardrailViolation
from sqlagent.domain.sql_policy import ALLOWED_NODE_TYPES, SqlPolicy

pytestmark = pytest.mark.unit

CATALOG = frozenset({"buyers", "suppliers", "tenders", "awards", "contracts", "tender_items"})
CAP = 1000

FRAGMENTS = [
    "SELECT",
    "WITH",
    "FROM",
    "WHERE",
    "GROUP BY",
    "ORDER BY",
    "LIMIT",
    "UNION",
    "JOIN",
    "ON",
    "AS",
    "tenders",
    "awards",
    "buyers",
    "*",
    "COUNT",
    "SUM",
    "(",
    ")",
    ",",
    ";",
    "'x'",
    "1",
    "--",
    "/*",
    "*/",
    "DROP TABLE",
    "read_csv",
    "current_date",
    "UNNEST",
]


@given(st.lists(st.sampled_from(FRAGMENTS), max_size=14))
def test_fuzzed_sql_is_either_rejected_or_uses_only_allowed_nodes(
    fragments: list[str],
) -> None:
    sql = " ".join(fragments)
    policy = SqlPolicy(CATALOG)

    try:
        validated = policy.validate(sql)
    except GuardrailViolation:
        return

    parsed = sqlglot.parse(validated.sql, read="duckdb")
    assert len(parsed) == 1
    root = parsed[0]
    assert root is not None
    assert all(type(node) in ALLOWED_NODE_TYPES for node in root.walk())


@given(st.text(alphabet="abc ()'\"%;-/*", max_size=40))
def test_arbitrary_text_never_escapes_the_policy(text: str) -> None:
    policy = SqlPolicy(CATALOG)

    try:
        validated = policy.validate(text)
    except GuardrailViolation:
        return

    parsed = sqlglot.parse(validated.sql, read="duckdb")
    assert len(parsed) == 1
    assert parsed[0] is not None
    assert validated.limit_applied <= CAP
