"""ETL behaviour on the synthetic OCDS mini fixture (D8, S1-S3)."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from sqlagent.adapters.warehouse.etl import (
    MANIFEST_SCHEMA,
    SOURCE_PINS,
    build_warehouse,
    verify_bundle,
)
from sqlagent.domain.errors import ConfigError, WarehouseUnavailable

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ocds_mini"

EXPECTED_ROWS = {
    "buyers": 2,
    "suppliers": 5,
    "tenders": 9,
    "awards": 8,
    "contracts": 4,
    "tender_items": 4,
}


def _rows(bundle: Path, table: str) -> list[tuple[object, ...]]:
    con = duckdb.connect()
    try:
        parquet = bundle / f"{table}.parquet"
        return con.execute("SELECT * FROM read_parquet(?)", [str(parquet)]).fetchall()
    finally:
        con.close()


def _query(bundle: Path, sql: str) -> list[tuple[object, ...]]:
    con = duckdb.connect()
    try:
        for table in EXPECTED_ROWS:
            parquet = str(bundle / f"{table}.parquet").replace("'", "''")
            con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{parquet}')")
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_build_writes_manifest_and_all_tables(tmp_path: Path) -> None:
    report = build_warehouse(FIXTURES, tmp_path, allow_drift=True)
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))

    assert manifest["schema"] == MANIFEST_SCHEMA
    assert report.tables == EXPECTED_ROWS
    assert manifest["source"]["members"]["main.csv"]["rows"] == 10
    for table, expected in EXPECTED_ROWS.items():
        entry = manifest["tables"][table]
        assert entry["rows"] == expected
        assert (tmp_path / entry["file"]).is_file()
        assert len(entry["sha256"]) == 64
        assert entry["fingerprint"]["distinct_keys"] == expected


def test_tender_rules_and_procurement_type_mapping(tmp_path: Path) -> None:
    build_warehouse(FIXTURES, tmp_path, allow_drift=True)

    rows = _query(
        tmp_path,
        "SELECT tender_id, process_code, procurement_type, status, planned_amount_usd, "
        "number_of_tenderers, category, is_competitive, title, description FROM tenders",
    )
    by_id = {row[0]: row for row in rows}
    assert len(rows) == 9
    assert "ocds-5wno2w-CE-20210000000009-1001" not in by_id  # planning-only release dropped

    first = by_id["ocds-5wno2w-CE-20210000000001-1001"]
    assert first[1] == "CE-20210000000001"
    assert first[2] == "catalogo_electronico"
    assert first[4] is None  # empty planned amount -> NULL
    assert first[8] == "Compra de útiles"
    assert first[9] == "Lápices y papel"
    assert first[7] is True

    types = {row[2] for row in rows}
    assert types == {
        "catalogo_electronico",
        "subasta_inversa",
        "menor_cuantia",
        "cotizacion",
        "contratacion_directa",
        "entre_entidades_publicas",
        "otros",
    }


def test_natural_person_pseudonymisation_and_provinces(tmp_path: Path) -> None:
    build_warehouse(FIXTURES, tmp_path, allow_drift=True)

    suppliers = _query(
        tmp_path,
        "SELECT supplier_id, supplier_name, supplier_kind, province, canton "
        "FROM suppliers ORDER BY supplier_id",
    )
    by_name = {row[1]: row for row in suppliers}
    natural = [row for row in suppliers if row[2] == "natural_person"]
    assert [row[0] for row in natural] == ["PN-000001", "PN-000002"]
    assert "Persona natural PN-000001" in by_name
    assert by_name["Persona natural PN-000001"][3] == "AZUAY"
    assert by_name["Persona natural PN-000002"][3] == "MANABI"
    assert "PEREZ JUAN" not in {row[1] for row in suppliers}
    assert by_name["ACME SA"][2:] == ("company", "PICHINCHA", "QUITO")
    unknown = [row for row in suppliers if row[2] == "other"]
    assert len(unknown) == 1
    assert unknown[0][0] == "ID-UNKNOWN"


def test_buyers_are_distinct_and_contracts_deduplicated(tmp_path: Path) -> None:
    build_warehouse(FIXTURES, tmp_path, allow_drift=True)

    buyers = _query(tmp_path, "SELECT buyer_id, province, canton FROM buyers ORDER BY buyer_id")
    assert buyers == [
        ("0102030405001", "GUAYAS", "GUAYAQUIL"),
        ("1790012345001", "PICHINCHA", "QUITO"),
    ]
    contract_ids = [row[0] for row in _query(tmp_path, "SELECT contract_id FROM contracts")]
    assert contract_ids.count("contract-2") == 1
    assert "contract-5" not in contract_ids  # planning-only tender
    item_ids = [row[0] for row in _query(tmp_path, "SELECT item_id FROM tender_items")]
    assert "item-5" not in item_ids


def test_manifest_fingerprints_and_verify(tmp_path: Path) -> None:
    build_warehouse(FIXTURES, tmp_path, allow_drift=True)
    report = verify_bundle(tmp_path)
    assert report.ok is True
    assert report.tables == EXPECTED_ROWS
    assert report.errors == ()

    manifest = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["tables"]["awards"]["fingerprint"]["sum_amount_cents"] == 84000
    assert manifest["tables"]["tenders"]["fingerprint"]["sum_amount_cents"] == 30275
    assert manifest["tables"]["contracts"]["fingerprint"]["sum_amount_cents"] == 25425


def test_verify_detects_tampering(tmp_path: Path) -> None:
    build_warehouse(FIXTURES, tmp_path, allow_drift=True)
    (tmp_path / "buyers.parquet").write_bytes(b"not parquet")
    report = verify_bundle(tmp_path)
    assert report.ok is False
    assert any("buyers.parquet" in error for error in report.errors)


def test_build_rejects_source_hash_drift_unless_allowed(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="SHA-256"):
        build_warehouse(FIXTURES, tmp_path, allow_drift=False)


def test_verify_reports_missing_bundle(tmp_path: Path) -> None:
    with pytest.raises(WarehouseUnavailable):
        verify_bundle(tmp_path)


def test_source_pins_cover_six_members() -> None:
    assert set(SOURCE_PINS.members) == {
        "main.csv",
        "awards.csv",
        "awards_suppliers.csv",
        "contracts.csv",
        "parties.csv",
        "tender_items.csv",
    }
    assert all(len(member.sha256) == 64 for member in SOURCE_PINS.members.values())
