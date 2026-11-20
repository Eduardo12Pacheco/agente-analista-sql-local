"""Read-only, locked-down DuckDB adapter: limits, errors and lookups (S15/S17)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from sqlagent.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from sqlagent.adapters.warehouse.materialize import ensure_warehouse
from sqlagent.application.ports import WarehouseLimits
from sqlagent.config import Settings
from sqlagent.domain.errors import QueryTimeoutError, SqlExecutionError
from sqlagent.domain.sql_policy import CATALOG_DEFAULT, SqlPolicy


@pytest.fixture
def warehouse_db(tmp_path: Path) -> Path:
    path = tmp_path / "raw.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE tenders(tender_id VARCHAR PRIMARY KEY, title VARCHAR)")
    con.execute("INSERT INTO tenders SELECT 'T' || i, 'Tender ' || i FROM range(1500) t(i)")
    con.execute(
        "CREATE TABLE buyers(buyer_id VARCHAR PRIMARY KEY, buyer_name VARCHAR, province VARCHAR)"
    )
    con.execute("CREATE TABLE awards(amount_usd DOUBLE)")
    con.executemany(
        "INSERT INTO buyers VALUES (?, ?, ?)",
        [
            ("1", "INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL", "PICHINCHA"),
            ("2", "GOBIERNO DE GUAYAS", "GUAYAS"),
            ("3", "MUNICIPIO DE CUENCA", "AZUAY"),
            ("4", "BANCO DEL PACIFICO", "GUAYAS"),
            ("5", "UNIVERSIDAD DE GUAYAQUIL", "GUAYAS"),
        ],
    )
    con.close()
    return path


def _warehouse(path: Path, **limits: object) -> DuckDbWarehouse:
    return DuckDbWarehouse(path, WarehouseLimits(**limits))  # type: ignore[arg-type]


def test_catalog_and_basic_execute(warehouse_db: Path) -> None:
    wh = _warehouse(warehouse_db)
    try:
        catalog = wh.catalog()
        assert set(catalog.tables) == {"tenders", "buyers", "awards"}
        assert catalog.tables["tenders"][0].name == "tender_id"

        policy = SqlPolicy(frozenset({"tenders"}))
        result = wh.execute(policy.validate("SELECT COUNT(*) AS n FROM tenders"))
        assert result.rows == ((1500,),)
        assert result.truncated is False
        assert result.columns[0].name == "n"
    finally:
        wh.close()


def test_cap_plus_one_marks_truncation(warehouse_db: Path) -> None:
    wh = _warehouse(warehouse_db, max_rows=1000)
    try:
        policy = SqlPolicy(CATALOG_DEFAULT, max_rows=2000)
        result = wh.execute(policy.validate("SELECT * FROM tenders"))
        assert result.truncated is True
        assert len(result.rows) == 1000
        assert result.row_count == 1000
    finally:
        wh.close()


def test_query_error_is_typed_and_trimmed(warehouse_db: Path) -> None:
    wh = _warehouse(warehouse_db)
    try:
        policy = SqlPolicy(frozenset({"tenders"}))
        with pytest.raises(SqlExecutionError) as excinfo:
            wh.execute(policy.validate("SELECT missing_column FROM tenders"))
        assert len(str(excinfo.value)) <= 300
    finally:
        wh.close()


def test_cross_join_is_stopped_by_the_watchdog(warehouse_db: Path) -> None:
    wh = _warehouse(warehouse_db, query_timeout_s=1.0)
    try:
        sql = (
            "SELECT SUM(LENGTH(a.title) + LENGTH(b.title) + LENGTH(c.title)) "
            "FROM tenders a, tenders b, tenders c"
        )
        with pytest.raises(QueryTimeoutError):
            wh.execute(SqlPolicy(frozenset({"tenders"})).validate(sql))
    finally:
        wh.close()


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO tenders VALUES ('X', 'x')",
        "CREATE TABLE evil(x INTEGER)",
        "COPY (SELECT 1) TO '/tmp/sqlagent-evil.csv'",
        "ATTACH '/tmp/sqlagent-evil.duckdb'",
        "INSTALL httpfs",
        "SELECT * FROM read_csv('/etc/hostname')",
        "SET enable_external_access=true",
    ],
)
def test_lockdown_blocks_escape_hatches(warehouse_db: Path, statement: str) -> None:
    wh = _warehouse(warehouse_db)
    try:
        with pytest.raises(duckdb.Error):
            wh.connection.execute(statement)
    finally:
        wh.close()


def test_lookup_values_is_accent_and_case_insensitive(warehouse_db: Path) -> None:
    wh = _warehouse(warehouse_db)
    try:
        assert wh.lookup_values("buyers.buyer_name", "iess seguridad social") == [
            "INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL"
        ]
        assert wh.lookup_values("buyers.province", "guayas") == ["GUAYAS"]
        with pytest.raises(ValueError, match="not a text column"):
            wh.lookup_values("awards.amount_usd", "1")
        with pytest.raises(ValueError, match="not in the catalog"):
            wh.lookup_values("tenders.nope", "x")
    finally:
        wh.close()


def test_info_reports_rows_and_manifest_hash(mini_bundle: Path, tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, warehouse_path=None)
    path = ensure_warehouse(settings, bundle_dir=mini_bundle)
    wh = DuckDbWarehouse(path, WarehouseLimits(), manifest_path=mini_bundle / "MANIFEST.json")
    try:
        info = wh.info()
        assert info.tables["tenders"] == 9
        assert len(info.manifest_sha256) == 64
        assert "datosabiertos.compraspublicas.gob.ec" in info.attribution
    finally:
        wh.close()
