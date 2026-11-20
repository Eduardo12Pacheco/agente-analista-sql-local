# ruff: noqa: S608
"""Materialise the bundled Parquet warehouse into a versioned DuckDB file (D9/S5).

The file name embeds the first eight hex characters of the manifest hash, so a
rebuilt bundle gets a fresh database and an existing one is reused without a
migration.  Creation is atomic: the database is built next to the target and
renamed into place only after every table and constraint exists.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import duckdb

from sqlagent.adapters.warehouse.etl import BUNDLE_DIR, MANIFEST_NAME, load_manifest
from sqlagent.config import Settings
from sqlagent.domain.errors import WarehouseUnavailable

_DDL: tuple[str, ...] = (
    """
    CREATE TABLE buyers (
        buyer_id VARCHAR PRIMARY KEY,
        buyer_name VARCHAR,
        province VARCHAR,
        canton VARCHAR
    )
    """,
    """
    CREATE TABLE suppliers (
        supplier_id VARCHAR PRIMARY KEY,
        supplier_name VARCHAR,
        supplier_kind VARCHAR,
        province VARCHAR,
        canton VARCHAR
    )
    """,
    """
    CREATE TABLE tenders (
        tender_id VARCHAR PRIMARY KEY,
        process_code VARCHAR,
        release_date DATE,
        buyer_id VARCHAR REFERENCES buyers(buyer_id),
        title VARCHAR,
        description VARCHAR,
        procurement_method VARCHAR,
        procurement_type VARCHAR,
        method_details VARCHAR,
        category VARCHAR,
        status VARCHAR,
        planned_amount_usd DOUBLE,
        number_of_tenderers INTEGER,
        is_competitive BOOLEAN
    )
    """,
    """
    CREATE TABLE awards (
        tender_id VARCHAR REFERENCES tenders(tender_id),
        award_id VARCHAR,
        supplier_id VARCHAR REFERENCES suppliers(supplier_id),
        amount_usd DOUBLE,
        status VARCHAR,
        PRIMARY KEY (tender_id, award_id)
    )
    """,
    """
    CREATE TABLE contracts (
        contract_id VARCHAR,
        tender_id VARCHAR REFERENCES tenders(tender_id),
        award_id VARCHAR,
        status VARCHAR,
        amount_usd DOUBLE,
        signed_date DATE,
        duration_days INTEGER
    )
    """,
    """
    CREATE TABLE tender_items (
        item_id VARCHAR PRIMARY KEY,
        tender_id VARCHAR REFERENCES tenders(tender_id),
        description VARCHAR,
        quantity DOUBLE,
        unit_name VARCHAR,
        unit_price_usd DOUBLE,
        cpc_code VARCHAR,
        cpc_description VARCHAR
    )
    """,
)

_COLUMNS: dict[str, tuple[str, ...]] = {
    "buyers": ("buyer_id", "buyer_name", "province", "canton"),
    "suppliers": ("supplier_id", "supplier_name", "supplier_kind", "province", "canton"),
    "tenders": (
        "tender_id",
        "process_code",
        "release_date",
        "buyer_id",
        "title",
        "description",
        "procurement_method",
        "procurement_type",
        "method_details",
        "category",
        "status",
        "planned_amount_usd",
        "number_of_tenderers",
        "is_competitive",
    ),
    "awards": ("tender_id", "award_id", "supplier_id", "amount_usd", "status"),
    "contracts": (
        "contract_id",
        "tender_id",
        "award_id",
        "status",
        "amount_usd",
        "signed_date",
        "duration_days",
    ),
    "tender_items": (
        "item_id",
        "tender_id",
        "description",
        "quantity",
        "unit_name",
        "unit_price_usd",
        "cpc_code",
        "cpc_description",
    ),
}


def _literal(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _manifest_sha256(manifest_path: Path) -> str:
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def _create_database(target: Path, bundle_dir: Path, manifest: dict[str, object]) -> None:
    tables = manifest["tables"]
    if not isinstance(tables, dict):  # pragma: no cover - load_manifest validates
        raise WarehouseUnavailable("warehouse manifest tables must be an object")
    con = duckdb.connect(str(target))
    try:
        con.execute("SET threads=1")
        con.execute("SET preserve_insertion_order=false")
        for statement in _DDL:
            con.execute(statement)
        for table, columns in _COLUMNS.items():
            entry = tables.get(table)
            if not isinstance(entry, dict):
                raise WarehouseUnavailable(f"manifest has no metadata for table {table!r}")
            parquet = bundle_dir / str(entry.get("file", f"{table}.parquet"))
            if not parquet.is_file():
                raise WarehouseUnavailable(f"bundled Parquet file is missing: {parquet.name}")
            projection = ", ".join(columns)
            con.execute(
                f"INSERT INTO {table} ({projection}) "
                f"SELECT {projection} FROM read_parquet({_literal(parquet)})"
            )
    finally:
        con.close()


def ensure_warehouse(settings: Settings, bundle_dir: Path = BUNDLE_DIR) -> Path:
    """Return the materialised DuckDB path, creating it atomically on first use."""

    if settings.warehouse_path is not None:
        path = Path(settings.warehouse_path).expanduser()
        if not path.is_file():
            raise WarehouseUnavailable(f"SQLAGENT_WAREHOUSE_PATH points to a missing file: {path}")
        return path

    bundle_dir = Path(bundle_dir)
    manifest_path = bundle_dir / MANIFEST_NAME
    manifest = load_manifest(bundle_dir)
    digest = _manifest_sha256(manifest_path)

    data_dir = Path(settings.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / f"warehouse-{digest[:8]}.duckdb"
    if target.is_file():
        return target

    handle, temporary_name = tempfile.mkstemp(
        prefix=f".warehouse-{digest[:8]}-", suffix=".duckdb", dir=data_dir
    )
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink(missing_ok=True)
    try:
        _create_database(temporary, bundle_dir, manifest)
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target
