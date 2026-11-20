"""Execution-accuracy equivalence rules for evaluation (D19).

Rows are compared positionally by column (names are ignored).  Ordered results
(``ORDER BY`` in the gold SQL) are compared as lists; unordered results as
multisets.  Floats use the documented absolute/relative tolerance and dates are
canonicalised to ISO strings.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal
from math import isfinite, isnan
from typing import Any

_NUMERIC_TOLERANCE = 0.01
_RELATIVE_TOLERANCE = 1e-6


def normalise_cell(value: Any) -> Any:
    """Return a canonical representation for comparison.

    Dates/times become ISO-8601 strings (so a ``DATE`` and its ISO text compare
    equal), ``Decimal`` becomes ``float`` and booleans are preserved.  Unknown
    objects pass through untouched so equality stays generic.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numbers_close(left: float, right: float) -> bool:
    if left == right:
        return True
    if isnan(left) and isnan(right):
        return True
    if not isfinite(left) or not isfinite(right):
        return False
    return abs(left - right) <= max(
        _RELATIVE_TOLERANCE * max(abs(left), abs(right)),
        _NUMERIC_TOLERANCE,
    )


def _cells_equal(left: Any, right: Any) -> bool:
    normalised_left = normalise_cell(left)
    normalised_right = normalise_cell(right)
    left_is_bool = isinstance(normalised_left, bool)
    right_is_bool = isinstance(normalised_right, bool)
    if left_is_bool or right_is_bool:
        return bool(left_is_bool and right_is_bool and normalised_left == normalised_right)
    left_is_int = isinstance(normalised_left, int)
    right_is_int = isinstance(normalised_right, int)
    if left_is_int and right_is_int:
        return bool(normalised_left == normalised_right)
    if _is_number(normalised_left) and _is_number(normalised_right):
        return _numbers_close(float(normalised_left), float(normalised_right))
    return bool(normalised_left == normalised_right)


def _rows_equal(left: Sequence[Any], right: Sequence[Any]) -> bool:
    if len(left) != len(right):
        return False
    return all(_cells_equal(a, b) for a, b in zip(left, right, strict=True))


def results_equivalent(
    gold_rows: Sequence[Sequence[Any]],
    pred_rows: Sequence[Sequence[Any]],
    ordered: bool,
) -> bool:
    """Return whether the predicted rows match the gold rows under D19 rules."""

    gold = [tuple(row) for row in gold_rows]
    predicted = [tuple(row) for row in pred_rows]
    if len(gold) != len(predicted):
        return False
    if ordered:
        return all(_rows_equal(g, p) for g, p in zip(gold, predicted, strict=True))

    unmatched = list(predicted)
    for gold_row in gold:
        for index, predicted_row in enumerate(unmatched):
            if _rows_equal(gold_row, predicted_row):
                del unmatched[index]
                break
        else:
            return False
    return True
