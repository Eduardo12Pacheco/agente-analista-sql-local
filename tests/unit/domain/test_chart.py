"""Chart chooser rules (D21), table-driven across every rule and column kind."""

from __future__ import annotations

import datetime as dt

import pytest

from sqlagent.domain.chart import ColumnKind, choose_chart, column_kind
from sqlagent.domain.models import ColumnInfo

pytestmark = pytest.mark.unit

LONG_LABEL = "x" * 19
MANY_CATEGORIES = 9
TOO_MANY_CATEGORIES = 31
SCATTER_MIN_ROWS = 5


def col(name: str, type_name: str) -> ColumnInfo:
    return ColumnInfo(name=name, type=type_name)


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [
        ("DATE", ColumnKind.TEMPORAL),
        ("TIMESTAMP", ColumnKind.TEMPORAL),
        ("TIMESTAMP WITH TIME ZONE", ColumnKind.TEMPORAL),
        ("INTEGER", ColumnKind.NUMERIC),
        ("BIGINT", ColumnKind.NUMERIC),
        ("DOUBLE", ColumnKind.NUMERIC),
        ("HUGEINT", ColumnKind.NUMERIC),
        ("DECIMAL(18,2)", ColumnKind.NUMERIC),
        ("BOOLEAN", ColumnKind.BOOLEAN),
        ("VARCHAR", ColumnKind.TEXT),
        ("CHAR(10)", ColumnKind.TEXT),
        ("BLOB", ColumnKind.OTHER),
        ("", ColumnKind.OTHER),
    ],
)
def test_column_kind_inference(type_name: str, expected: ColumnKind) -> None:
    assert column_kind(type_name) is expected


def test_empty_result_has_no_chart() -> None:
    spec = choose_chart([col("label", "VARCHAR"), col("n", "BIGINT")], [], "Result")

    assert spec.kind == "none"
    assert spec.reason == "no_rows"
    assert spec.x is None
    assert spec.y == ()
    assert spec.truncated_categories is False


def test_single_row_single_numeric_is_a_kpi() -> None:
    spec = choose_chart([col("label", "VARCHAR"), col("n", "BIGINT")], [("total", 42)], "Result")

    assert spec.kind == "kpi"
    assert spec.x is None
    assert spec.y == ("n",)
    assert spec.title == "Result"
    assert spec.reason == "single_value"


def test_single_row_with_two_numerics_is_not_a_kpi() -> None:
    spec = choose_chart([col("a", "BIGINT"), col("b", "DOUBLE")], [(1, 2.0)], "Result")

    assert spec.kind == "none"
    assert spec.reason == "not_chartable"


def test_temporal_first_column_yields_a_line_chart() -> None:
    rows = [
        (dt.date(2021, 1, 1), 10),
        (dt.date(2021, 2, 1), 20),
    ]

    spec = choose_chart([col("month", "DATE"), col("n", "BIGINT")], rows, "Result")

    assert spec.kind == "line"
    assert spec.x == "month"
    assert spec.y == ("n",)
    assert spec.series is None
    assert spec.reason == "time_series"


def test_line_chart_uses_a_low_cardinality_text_series() -> None:
    rows = [
        (dt.date(2021, 1, 1), 10, "A"),
        (dt.date(2021, 2, 1), 20, "B"),
        (dt.date(2021, 3, 1), 30, "A"),
    ]

    spec = choose_chart(
        [col("month", "DATE"), col("n", "BIGINT"), col("status", "VARCHAR")],
        rows,
        "Result",
    )

    assert spec.kind == "line"
    assert spec.series == "status"


def test_line_chart_ignores_a_high_cardinality_text_column() -> None:
    rows = [(dt.date(2021, 1, 1), 10, f"label-{index}") for index in range(7)]

    spec = choose_chart(
        [col("month", "DATE"), col("n", "BIGINT"), col("label", "VARCHAR")],
        rows,
        "Result",
    )

    assert spec.kind == "line"
    assert spec.series is None


def test_line_chart_handles_unhashable_series_values() -> None:
    rows = [
        (dt.date(2021, 1, 1), 10, ["a"]),
        (dt.date(2021, 2, 1), 20, ["b"]),
    ]

    spec = choose_chart(
        [col("month", "DATE"), col("n", "BIGINT"), col("tag", "VARCHAR")],
        rows,
        "Result",
    )

    assert spec.kind == "line"
    assert spec.series == "tag"


def test_temporal_column_must_be_first_for_line_chart() -> None:
    rows = [(1, dt.date(2021, 1, 1)), (2, dt.date(2021, 2, 1))]

    spec = choose_chart([col("n", "BIGINT"), col("month", "DATE")], rows, "Result")

    assert spec.kind == "none"
    assert spec.reason == "not_chartable"


def test_text_and_numeric_yield_a_vertical_bar_chart() -> None:
    rows = [("Guayas", 10), ("Pichincha", 20), ("Azuay", 30)]

    spec = choose_chart([col("province", "VARCHAR"), col("n", "BIGINT")], rows, "Result")

    assert spec.kind == "bar"
    assert spec.x == "province"
    assert spec.y == ("n",)
    assert spec.reason == "category_breakdown"
    assert spec.truncated_categories is False


def test_long_labels_switch_to_horizontal_bars() -> None:
    rows = [(LONG_LABEL, 10), ("short", 20)]

    spec = choose_chart([col("buyer_name", "VARCHAR"), col("n", "BIGINT")], rows, "Result")

    assert spec.kind == "hbar"


def test_more_than_eight_categories_switch_to_horizontal_bars() -> None:
    rows = [(f"category-{index}", index) for index in range(MANY_CATEGORIES)]

    spec = choose_chart([col("category", "VARCHAR"), col("n", "BIGINT")], rows, "Result")

    assert spec.kind == "hbar"


def test_more_than_thirty_categories_truncates_the_chart() -> None:
    rows = [(f"category-{index}", index) for index in range(TOO_MANY_CATEGORIES)]

    spec = choose_chart([col("category", "VARCHAR"), col("n", "BIGINT")], rows, "Result")

    assert spec.kind == "bar"
    assert spec.x == "category"
    assert spec.y == ("n",)
    assert spec.truncated_categories is True
    assert spec.reason == "category_breakdown_truncated"


def test_two_numerics_without_categorical_columns_yield_a_scatter() -> None:
    rows = [(index, index * 2.0) for index in range(SCATTER_MIN_ROWS)]

    spec = choose_chart([col("x", "BIGINT"), col("y", "DOUBLE")], rows, "Correlation")

    assert spec.kind == "scatter"
    assert spec.x == "x"
    assert spec.y == ("y",)
    assert spec.reason == "numeric_correlation"
    assert spec.title == "Correlation"


def test_scatter_requires_at_least_five_rows() -> None:
    rows = [(index, index * 2.0) for index in range(SCATTER_MIN_ROWS - 1)]

    spec = choose_chart([col("x", "BIGINT"), col("y", "DOUBLE")], rows, "Result")

    assert spec.kind == "none"


def test_boolean_and_numeric_columns_are_not_chartable() -> None:
    rows = [(True, 1), (False, 2)]

    spec = choose_chart([col("flag", "BOOLEAN"), col("n", "BIGINT")], rows, "Result")

    assert spec.kind == "none"
    assert spec.reason == "not_chartable"


def test_multiple_text_columns_use_the_first_as_the_category_axis() -> None:
    rows = [("Guayas", "Guayaquil", 10), ("Azuay", "Cuenca", 20)]

    spec = choose_chart(
        [col("province", "VARCHAR"), col("canton", "VARCHAR"), col("n", "BIGINT")],
        rows,
        "Result",
    )

    assert spec.kind == "bar"
    assert spec.x == "province"
    assert spec.y == ("n",)


def test_none_labels_do_not_break_the_chooser() -> None:
    rows = [(None, 10), ("Pichincha", 20)]

    spec = choose_chart([col("province", "VARCHAR"), col("n", "BIGINT")], rows, "Result")

    assert spec.kind == "bar"
    assert spec.x == "province"


def test_ragged_rows_do_not_break_the_chooser() -> None:
    rows = [("only-label",), ("province", 20, "extra"), ("province",)]

    spec = choose_chart([col("province", "VARCHAR"), col("n", "BIGINT")], rows, "Result")

    assert spec.kind == "bar"
    assert spec.y == ("n",)
