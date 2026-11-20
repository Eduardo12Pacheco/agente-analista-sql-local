"""Warehouse materialisation: atomic, versioned and reused (S5/D9)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest

from sqlagent.adapters.warehouse.materialize import ensure_warehouse
from sqlagent.config import Settings
from sqlagent.domain.errors import WarehouseUnavailable

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ocds_mini"


def _settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", warehouse_path=None)


def test_materialises_with_manifest_hash_name(mini_bundle: Path, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    path = ensure_warehouse(settings, bundle_dir=mini_bundle)

    manifest_sha = hashlib.sha256((mini_bundle / "MANIFEST.json").read_bytes()).hexdigest()
    assert path == settings.data_dir / f"warehouse-{manifest_sha[:8]}.duckdb"
    assert path.is_file()
    con = duckdb.connect(str(path), read_only=True)
    try:
        assert con.execute("SELECT COUNT(*) FROM tenders").fetchone() == (9,)
        assert con.execute("SELECT COUNT(*) FROM suppliers").fetchone() == (5,)
    finally:
        con.close()


def test_reuses_existing_materialisation(mini_bundle: Path, tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = ensure_warehouse(settings, bundle_dir=mini_bundle)
    mtime = first.stat().st_mtime_ns
    second = ensure_warehouse(settings, bundle_dir=mini_bundle)
    assert second == first
    assert second.stat().st_mtime_ns == mtime


def test_pk_and_fk_declarations_present(mini_bundle: Path, tmp_path: Path) -> None:
    path = ensure_warehouse(_settings(tmp_path), bundle_dir=mini_bundle)
    con = duckdb.connect(str(path), read_only=True)
    try:
        constraints = con.execute(
            "SELECT table_name, constraint_type FROM duckdb_constraints() ORDER BY 1, 2"
        ).fetchall()
    finally:
        con.close()
    assert ("tenders", "PRIMARY KEY") in constraints
    assert ("tenders", "FOREIGN KEY") in constraints
    assert ("awards", "FOREIGN KEY") in constraints


def test_warehouse_path_override_requires_an_existing_file(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.duckdb"
    settings = Settings(data_dir=tmp_path, warehouse_path=explicit)
    with pytest.raises(WarehouseUnavailable, match="WAREHOUSE_PATH"):
        ensure_warehouse(settings, bundle_dir=FIXTURES)
    explicit.write_bytes(b"")
    assert ensure_warehouse(settings, bundle_dir=FIXTURES) == explicit


def test_missing_manifest_is_a_typed_error(tmp_path: Path) -> None:
    with pytest.raises(WarehouseUnavailable, match="MANIFEST"):
        ensure_warehouse(_settings(tmp_path), bundle_dir=tmp_path)


def test_manifest_schema_is_checked(mini_bundle: Path, tmp_path: Path) -> None:
    broken = tmp_path / "bundle"
    broken.mkdir()
    manifest = json.loads((mini_bundle / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest["schema"] = "wrong"
    (broken / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WarehouseUnavailable, match="schema"):
        ensure_warehouse(_settings(tmp_path), bundle_dir=broken)
