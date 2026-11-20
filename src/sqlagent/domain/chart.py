"""Pure chart selection (D21).

Rules are evaluated in order and the first match wins.  The chooser never reads
the database: it only inspects declared DuckDB column types and the result rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from sqlagent.domain.models import ChartSpec, ColumnInfo

_MAX_CATEGORIES = 30
_MAX_VERTICAL_CATEGORIES = 8
_MAX_VERTICAL_LABEL = 18
_MAX_SERIES_DISTINCT = 6
_SCATTER_COLUMNS = 2
_SCATTER_MIN_ROWS = 5


class ColumnKind(StrEnum):
    """Coarse column kinds derived from DuckDB type strings (D21)."""

    TEMPORAL = "temporal"
    NUMERIC = "numeric"
    BOOLEAN = "boolean"
    TEXT = "text"
    OTHER = "other"


_NUMERIC_TYPES = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
        "INT",
        "INT2",
        "INT4",
        "INT8",
        "FLOAT",
        "REAL",
        "DOUBLE",
        "DOUBLE PRECISION",
        "DECIMAL",
        "NUMERIC",
        "DEC",
    }
)
_BOOLEAN_TYPES = frozenset({"BOOLEAN", "BOOL"})
_TEXT_TYPES = frozenset({"VARCHAR", "CHAR", "BPCHAR", "TEXT", "STRING"})


def column_kind(type_name: str) -> ColumnKind:
    """Map a DuckDB type string to a chart-relevant column kind."""

    base = type_name.strip().upper().split("(", 1)[0].strip()
    if base.startswith("DATE") or base.startswith("TIMESTAMP"):
        return ColumnKind.TEMPORAL
    if base in _NUMERIC_TYPES:
        return ColumnKind.NUMERIC
    if base in _BOOLEAN_TYPES:
        return ColumnKind.BOOLEAN
    if base in _TEXT_TYPES:
        return ColumnKind.TEXT
    return ColumnKind.OTHER


def _names(columns: Sequence[ColumnInfo], indices: Sequence[int]) -> tuple[str, ...]:
    return tuple(columns[index].name for index in indices)


def _cell(rows: Sequence[Sequence[Any]], row_index: int, column_index: int) -> Any:
    row = rows[row_index]
    if column_index < len(row):
        return row[column_index]
    return None


def _max_label_length(rows: Sequence[Sequence[Any]], column_index: int) -> int:
    longest = 0
    for row_index in range(len(rows)):
        value = _cell(rows, row_index, column_index)
        if value is not None:
            longest = max(longest, len(str(value)))
    return longest


def _distinct_count(rows: Sequence[Sequence[Any]], column_index: int) -> int:
    distinct: set[Any] = set()
    for row_index in range(len(rows)):
        value = _cell(rows, row_index, column_index)
        try:
            hash(value)
        except TypeError:
            value = repr(value)
        distinct.add(value)
    return len(distinct)


def _series_column(
    columns: Sequence[ColumnInfo],
    rows: Sequence[Sequence[Any]],
    text_indices: Sequence[int],
) -> str | None:
    candidates = [
        columns[index].name
        for index in text_indices
        if _distinct_count(rows, index) <= _MAX_SERIES_DISTINCT
    ]
    return candidates[0] if len(candidates) == 1 else None


def choose_chart(  # noqa: PLR0911 - one return per ordered D21 rule
    columns: Sequence[ColumnInfo],
    rows: Sequence[Sequence[Any]],
    language_neutral_title: str,
) -> ChartSpec:
    """Choose the best chart for a result set, or ``none`` when none fits."""

    kinds = [column_kind(column.type) for column in columns]
    numeric = [index for index, kind in enumerate(kinds) if kind is ColumnKind.NUMERIC]
    text = [index for index, kind in enumerate(kinds) if kind is ColumnKind.TEXT]
    temporal = [index for index, kind in enumerate(kinds) if kind is ColumnKind.TEMPORAL]
    row_count = len(rows)

    if row_count == 0:
        return ChartSpec(kind="none", title=language_neutral_title, reason="no_rows")

    if row_count == 1 and len(numeric) == 1:
        return ChartSpec(
            kind="kpi",
            y=_names(columns, numeric),
            title=language_neutral_title,
            reason="single_value",
        )

    if temporal and temporal[0] == 0 and numeric:
        return ChartSpec(
            kind="line",
            x=columns[0].name,
            y=_names(columns, numeric),
            series=_series_column(columns, rows, text),
            title=language_neutral_title,
            reason="time_series",
        )

    if text and numeric:
        category_index = text[0]
        y = _names(columns, numeric)
        if row_count > _MAX_CATEGORIES:
            return ChartSpec(
                kind="bar",
                x=columns[category_index].name,
                y=y,
                title=language_neutral_title,
                reason="category_breakdown_truncated",
                truncated_categories=True,
            )
        long_labels = _max_label_length(rows, category_index) > _MAX_VERTICAL_LABEL
        horizontal = long_labels or row_count > _MAX_VERTICAL_CATEGORIES
        return ChartSpec(
            kind="hbar" if horizontal else "bar",
            x=columns[category_index].name,
            y=y,
            title=language_neutral_title,
            reason="category_breakdown",
        )

    if (
        len(numeric) == _SCATTER_COLUMNS
        and not text
        and not temporal
        and row_count >= _SCATTER_MIN_ROWS
    ):
        return ChartSpec(
            kind="scatter",
            x=columns[numeric[0]].name,
            y=(columns[numeric[1]].name,),
            title=language_neutral_title,
            reason="numeric_correlation",
        )

    return ChartSpec(kind="none", title=language_neutral_title, reason="not_chartable")
