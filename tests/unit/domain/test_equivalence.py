"""Execution-accuracy equivalence rules (D19)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from sqlagent.domain.equivalence import normalise_cell, results_equivalent

pytestmark = pytest.mark.unit

Rows = list[list[object]]


def test_identical_rows_are_equivalent_in_both_modes() -> None:
    rows: Rows = [[1, "Guayas"], [2, "Azuay"]]

    assert results_equivalent(rows, rows, ordered=True)
    assert results_equivalent(rows, rows, ordered=False)


def test_unordered_comparison_ignores_row_order() -> None:
    gold: Rows = [[1, "Guayas"], [2, "Azuay"]]
    predicted: Rows = [[2, "Azuay"], [1, "Guayas"]]

    assert results_equivalent(gold, predicted, ordered=True) is False
    assert results_equivalent(gold, predicted, ordered=False) is True


def test_unordered_comparison_excludes_column_names_and_matches_by_position() -> None:
    gold: Rows = [["Guayas", 1]]
    predicted: Rows = [[1, "Guayas"]]

    assert results_equivalent(gold, predicted, ordered=True) is False
    assert results_equivalent(gold, predicted, ordered=False) is False


def test_extra_or_missing_columns_are_a_mismatch() -> None:
    assert results_equivalent([[1, 2]], [[1]], ordered=False) is False
    assert results_equivalent([[1]], [[1, 2]], ordered=False) is False


def test_row_count_mismatch_is_a_mismatch() -> None:
    assert results_equivalent([[1]], [], ordered=False) is False
    assert results_equivalent([], [[1]], ordered=False) is False


def test_two_empty_results_are_equivalent() -> None:
    assert results_equivalent([], [], ordered=True)
    assert results_equivalent([], [], ordered=False)


def test_float_tolerance() -> None:
    assert results_equivalent([[1.0]], [[1.005]], ordered=True) is True
    assert results_equivalent([[1.0]], [[1.02]], ordered=True) is False
    assert results_equivalent([[1_000_000.0]], [[1_000_000.5]], ordered=True) is True
    assert results_equivalent([[1_000_000.0]], [[1_000_002.0]], ordered=True) is False


def test_integer_columns_compare_exactly_not_with_float_tolerance() -> None:
    assert results_equivalent([[1_000_000]], [[1_000_001]], ordered=True) is False
    assert results_equivalent([[1_000_000]], [[1_000_000]], ordered=True)


def test_booleans_never_equal_integers() -> None:
    assert results_equivalent([[True]], [[1]], ordered=True) is False
    assert results_equivalent([[False]], [[0]], ordered=True) is False
    assert results_equivalent([[True]], [[True]], ordered=True)


def test_integer_and_decimal_compare_numerically() -> None:
    assert results_equivalent([[1]], [[1.0]], ordered=True)
    assert results_equivalent([[Decimal("1.50")]], [[1.5]], ordered=True)
    assert results_equivalent([[Decimal("1.50")]], [[1.6]], ordered=True) is False


def test_nulls_only_match_nulls() -> None:
    assert results_equivalent([[None]], [[None]], ordered=True)
    assert results_equivalent([[None]], [[0]], ordered=True) is False


def test_dates_compare_as_iso_strings() -> None:
    assert results_equivalent([[dt.date(2021, 1, 4)]], [["2021-01-04"]], ordered=True)
    assert results_equivalent([[dt.date(2021, 1, 4)]], [["2021-01-05"]], ordered=True) is False


def test_datetimes_compare_as_iso_strings() -> None:
    value = dt.datetime(2021, 1, 4, 12, 30, 5)

    assert results_equivalent([[value]], [[value.isoformat()]], ordered=True)


def test_unordered_matching_handles_duplicate_rows() -> None:
    assert results_equivalent([[1], [1], [2]], [[2], [1], [1]], ordered=False)
    assert results_equivalent([[1], [1], [2]], [[1], [2], [2]], ordered=False) is False


def test_ragged_and_empty_rows_are_handled() -> None:
    assert results_equivalent([[1, 2], [3]], [[3], [1, 2]], ordered=False)
    assert results_equivalent([[1, 2], [3]], [[1, 2], [3, 4]], ordered=False) is False
    assert results_equivalent([[]], [[]], ordered=True)


def test_nan_matches_itself_but_not_a_number() -> None:
    nan = float("nan")

    assert results_equivalent([[nan]], [[nan]], ordered=True)
    assert results_equivalent([[nan]], [[1.0]], ordered=True) is False


def test_normalise_cell_canonicalises_dates_and_decimals() -> None:
    assert normalise_cell(dt.date(2021, 1, 4)) == "2021-01-04"
    assert normalise_cell(dt.datetime(2021, 1, 4, 12, 30)) == "2021-01-04T12:30:00"
    assert normalise_cell(Decimal("2.50")) == 2.5  # noqa: PLR2004
    assert normalise_cell(None) is None
    assert normalise_cell(True) is True
    assert normalise_cell("text") == "text"
    assert normalise_cell(7) == 7  # noqa: PLR2004


def test_normalise_cell_leaves_unknown_objects_untouched() -> None:
    marker = object()

    assert normalise_cell(marker) is marker
