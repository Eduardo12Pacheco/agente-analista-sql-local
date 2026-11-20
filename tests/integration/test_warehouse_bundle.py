"""Committed SERCOP 2021 warehouse bundle: integrity, privacy and FKs (S1-S5)."""

from __future__ import annotations

import time
from pathlib import Path

import duckdb
import pytest

from sqlagent.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from sqlagent.adapters.warehouse.etl import BUNDLE_DIR, verify_bundle
from sqlagent.adapters.warehouse.materialize import ensure_warehouse
from sqlagent.application.ports import WarehouseLimits
from sqlagent.config import Settings
from sqlagent.domain.sql_policy import SqlPolicy

pytestmark = pytest.mark.integration

EXPECTED = {
    "tenders": 121_072,
    "buyers": 2_641,
    "suppliers": 10_217,
    "awards": 121_736,
    "tender_items": 49_628,
    "contracts": 117_492,
}

TEXT_TYPES = {"VARCHAR", "TEXT", "STRING"}


def test_bundle_verify_and_size() -> None:
    report = verify_bundle(BUNDLE_DIR)
    assert report.ok, report.errors
    assert report.tables == EXPECTED
    total = sum(path.stat().st_size for path in BUNDLE_DIR.glob("*.parquet"))
    assert total <= 8_000_000, f"parquet bundle is {total} bytes"


def test_privacy_scan_of_every_varchar_cell() -> None:
    con = duckdb.connect()
    # Boundary excludes hyphens: OCDS process codes legitimately contain
    # 13-digit runs (e.g. ocds-...-CE-20210001948001-...) that are not RUCs.
    pattern = r"(^|[^0-9-])\d{2}[0-5]\d{8}001([^0-9-]|$)"
    try:
        for table in ("buyers", "suppliers", "tenders", "awards", "contracts", "tender_items"):
            file = BUNDLE_DIR / f"{table}.parquet"
            columns = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(file)]).fetchall()
            text_columns = [
                row[0] for row in columns if str(row[1]).upper().split("(")[0] in TEXT_TYPES
            ]
            for column in text_columns:
                match = con.execute(
                    f'SELECT "{column}" FROM read_parquet(?) '
                    f'WHERE regexp_matches(CAST("{column}" AS VARCHAR), ?) LIMIT 1',
                    [str(file), pattern],
                ).fetchone()
                assert match is None, f"{table}.{column} leaks a natural-person RUC"
        bad_name = con.execute(
            "SELECT supplier_name FROM read_parquet(?) WHERE supplier_kind = 'natural_person' "
            "AND supplier_name NOT LIKE 'Persona natural PN-%' LIMIT 1",
            [str(BUNDLE_DIR / "suppliers.parquet")],
        ).fetchone()
        assert bad_name is None
    finally:
        con.close()


def test_materialisation_timing_and_fk_integrity(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, warehouse_path=None)
    started = time.perf_counter()
    path = ensure_warehouse(settings)
    elapsed = time.perf_counter() - started
    assert elapsed < 30, f"first materialisation took {elapsed:.1f}s"

    con = duckdb.connect(str(path), read_only=True)
    try:
        checks = {
            "tenders.buyer_id": (
                "SELECT COUNT(*) FROM tenders t LEFT JOIN buyers b USING (buyer_id) "
                "WHERE b.buyer_id IS NULL"
            ),
            "awards.tender_id": (
                "SELECT COUNT(*) FROM awards a LEFT JOIN tenders t USING (tender_id) "
                "WHERE t.tender_id IS NULL"
            ),
            "awards.supplier_id": (
                "SELECT COUNT(*) FROM awards a LEFT JOIN suppliers s USING (supplier_id) "
                "WHERE s.supplier_id IS NULL"
            ),
            "contracts.tender_id": (
                "SELECT COUNT(*) FROM contracts c LEFT JOIN tenders t USING (tender_id) "
                "WHERE t.tender_id IS NULL"
            ),
            "tender_items.tender_id": (
                "SELECT COUNT(*) FROM tender_items i LEFT JOIN tenders t USING (tender_id) "
                "WHERE t.tender_id IS NULL"
            ),
        }
        for label, sql in checks.items():
            assert con.execute(sql).fetchone() == (0,), f"orphans in {label}"
    finally:
        con.close()


def test_adapter_executes_against_the_real_bundle(tmp_path: Path) -> None:
    path = ensure_warehouse(Settings(data_dir=tmp_path, warehouse_path=None))
    wh = DuckDbWarehouse(path, WarehouseLimits(), manifest_path=BUNDLE_DIR / "MANIFEST.json")
    try:
        result = wh.execute(SqlPolicy().validate("SELECT COUNT(*) AS n FROM tenders"))
        assert result.rows == ((121_072,),)
        info = wh.info()
        assert info.tables["suppliers"] == 10_217
        assert wh.lookup_values("buyers.buyer_name", "iess seguridad social")[0] == (
            "INSTITUTO ECUATORIANO DE SEGURIDAD SOCIAL"
        )
        assert wh.lookup_values("buyers.province", "guayas") == ["GUAYAS"]
    finally:
        wh.close()
