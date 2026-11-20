"""Hypothesis properties for the pure domain rules (D29)."""

from __future__ import annotations

import datetime as dt
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sqlagent.domain.chart import choose_chart
from sqlagent.domain.equivalence import results_equivalent
from sqlagent.domain.language import detect_language
from sqlagent.domain.models import ColumnInfo, Language

pytestmark = pytest.mark.unit

CELLS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**6), max_value=10**6),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=20),
    st.dates(),
    st.datetimes(),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=3),
)

COLUMN_TYPES = st.one_of(
    st.sampled_from(
        [
            "DATE",
            "TIMESTAMP",
            "INTEGER",
            "BIGINT",
            "DOUBLE",
            "DECIMAL(18,2)",
            "BOOLEAN",
            "VARCHAR",
            "BLOB",
            "",
        ]
    ),
    st.text(max_size=12),
)

COLUMNS = st.lists(
    st.builds(ColumnInfo, name=st.text(max_size=8), type=COLUMN_TYPES),
    max_size=6,
)

ROWS = st.lists(st.lists(CELLS, max_size=6), max_size=40)

ROW_SETS = st.lists(st.lists(CELLS, max_size=4), max_size=20)


@given(columns=COLUMNS, rows=ROWS)
def test_choose_chart_is_total_and_only_references_existing_columns(
    columns: list[ColumnInfo], rows: list[list[object]]
) -> None:
    spec = choose_chart(columns, rows, "Result")

    names = {column.name for column in columns}
    assert spec.kind in {"none", "kpi", "line", "bar", "hbar", "scatter"}
    if spec.x is not None:
        assert spec.x in names
    assert set(spec.y) <= names
    if spec.series is not None:
        assert spec.series in names


@given(rows=ROW_SETS)
def test_results_equivalent_is_reflexive(rows: list[list[object]]) -> None:
    assert results_equivalent(rows, rows, ordered=True)
    assert results_equivalent(rows, rows, ordered=False)


@given(rows=ROW_SETS, seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_unordered_equivalence_is_permutation_invariant(
    rows: list[list[object]], seed: int
) -> None:
    shuffled = [list(row) for row in rows]
    random.Random(seed).shuffle(shuffled)  # noqa: S311 - deterministic test shuffle

    assert results_equivalent(rows, shuffled, ordered=False)


@given(text=st.text())
def test_detect_language_is_total(text: str) -> None:
    assert detect_language(text) in {Language.ES, Language.EN}


def test_detect_language_examples_are_stable() -> None:
    assert detect_language("¿Cuántos procesos hay?") is Language.ES
    assert detect_language("How many tenders are there?") is Language.EN


@given(date_value=st.dates(), seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_date_iso_rendering_is_stable(date_value: dt.date, seed: int) -> None:
    rows = [[date_value]]
    if seed % 2:
        rows = [[date_value.isoformat()]]

    assert results_equivalent([[date_value]], rows, ordered=True)
