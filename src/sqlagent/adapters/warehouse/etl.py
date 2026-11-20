# ruff: noqa: S608, RUF001
"""SERCOP OCDS 2021 ETL, Parquet bundle writer and integrity verifier (D6/D8/D9).

The ETL is a single deterministic DuckDB session (``threads=1``): every table is
projected and normalised with SQL, ordered by its key and written as zstd-19
Parquet.  Natural-person suppliers are pseudonymised at the source of truth so
the committed bundle never contains a natural person's name or RUC.  A manifest
records file hashes, row counts, fingerprints and the upstream pins.
"""

from __future__ import annotations

import csv
import hashlib
import json
import posixpath
import tarfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version as _package_version
from pathlib import Path
from typing import Any, Final

import duckdb
import httpx

from sqlagent import __version__
from sqlagent.domain.errors import ConfigError, WarehouseUnavailable

MANIFEST_SCHEMA: Final = "sqlagent.warehouse-manifest/v1"
MANIFEST_NAME: Final = "MANIFEST.json"
BUNDLE_DIR: Final = Path(__file__).resolve().parents[2] / "resources" / "warehouse"
ATTRIBUTION: Final = (
    "Contains data from SERCOP, Ecuador "
    "(https://datosabiertos.compraspublicas.gob.ec), CC BY 3.0 EC; "
    "filtered, normalised, pseudonymised"
)
LICENSE: Final = "CC BY 3.0 Ecuador"


@dataclass(frozen=True, slots=True)
class MemberPin:
    """One pinned upstream CSV member."""

    name: str
    rows: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SourcePins:
    """Pinned upstream artefact and the six members the ETL consumes."""

    year: int
    url: str
    tarball_sha256: str
    members: Mapping[str, MemberPin]


SOURCE_PINS: Final = SourcePins(
    year=2021,
    url="https://data.open-contracting.org/en/publication/110/download?name=2021.csv.tar.gz",
    tarball_sha256="e1fbc3c855a4c85f2077542cbce977ab5ac882fc11744f7042bc81d5a8f426fe",
    members={
        "main.csv": MemberPin(
            "main.csv", 122_277, "eb3c05fdf955dbd3879e372f3e6ce54f7f8b199efd45bb355d754aeba3e53f00"
        ),
        "awards.csv": MemberPin(
            "awards.csv",
            121_736,
            "2622dbe34c5ab30a6b93de76b817884ad19484ee6557957faf8e73897beefe4d",
        ),
        "awards_suppliers.csv": MemberPin(
            "awards_suppliers.csv",
            121_736,
            "cbfaae3cf405fccf72d4de9e31003b96ee19323eb5f7bd0e31965d194fe0d4ab",
        ),
        "contracts.csv": MemberPin(
            "contracts.csv",
            117_492,
            "6d944118c5d0876279033dd39e9c842df20be759cb5ef4faedc7b720e12b71ee",
        ),
        "parties.csv": MemberPin(
            "parties.csv",
            293_287,
            "5da114e85818189bc63b623b6fd2863443247f6097726e72d065054db0cc0da8",
        ),
        "tender_items.csv": MemberPin(
            "tender_items.csv",
            49_628,
            "0844e18c3d1e7b15bbfb63609d1ba83d059c6eab44d83546802803c7a5ae0fe8",
        ),
    },
)

TABLE_ORDER: Final = ("buyers", "suppliers", "tenders", "awards", "contracts", "tender_items")

#: Monetary column used for the per-table cents fingerprint (``None`` = no amount).
AMOUNT_COLUMNS: Final[Mapping[str, str | None]] = {
    "buyers": None,
    "suppliers": None,
    "tenders": "planned_amount_usd",
    "awards": "amount_usd",
    "contracts": "amount_usd",
    "tender_items": "unit_price_usd",
}

#: Deterministic key used for the distinct-key fingerprint and ORDER BY.
KEY_COLUMNS: Final[Mapping[str, tuple[str, ...]]] = {
    "buyers": ("buyer_id",),
    "suppliers": ("supplier_id",),
    "tenders": ("tender_id",),
    "awards": ("tender_id", "award_id"),
    "contracts": ("contract_id",),
    "tender_items": ("item_id",),
}


@dataclass(frozen=True, slots=True)
class BuildReport:
    """Outcome of one ``build_warehouse`` run."""

    tables: Mapping[str, int]
    manifest_path: Path
    manifest_sha256: str
    total_bytes: int
    source_dir: Path


@dataclass(frozen=True, slots=True)
class VerifyReport:
    """Outcome of ``verify_bundle``; ``ok`` is true only with no errors."""

    ok: bool
    tables: Mapping[str, int]
    errors: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.ok


@dataclass(slots=True)
class _BuildContext:
    connection: duckdb.DuckDBPyConnection
    source_dir: Path
    errors: list[str] = field(default_factory=list)


def _literal(value: str | Path) -> str:
    """Render a SQL string literal (paths cannot use bind parameters in DDL)."""

    return "'" + str(value).replace("'", "''") + "'"


def _read_csv(path: Path) -> str:
    return f"read_csv({_literal(path)}, all_varchar=true, sample_size=-1)"


def _collapse(expression: str) -> str:
    """Trim and collapse whitespace runs to a single space (D8)."""

    return f"regexp_replace(trim(CAST({expression} AS VARCHAR)), '[[:space:]]+', ' ', 'g')"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_rows(path: Path) -> int:
    """Count CSV records (quoted fields may contain embedded newlines)."""

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def _source_layout(source_dir: Path) -> Path:
    if (source_dir / "main.csv").is_file():
        return source_dir
    nested = source_dir / str(SOURCE_PINS.year)
    if (nested / "main.csv").is_file():
        return nested
    raise WarehouseUnavailable(f"OCDS source directory does not contain main.csv: {source_dir}")


def check_source_members(source_dir: Path, *, allow_drift: bool = False) -> dict[str, MemberPin]:
    """Hash the six consumed members and compare them with the dated pins."""

    layout = _source_layout(source_dir)
    members: dict[str, MemberPin] = {}
    mismatches: list[str] = []
    for name, pin in SOURCE_PINS.members.items():
        path = layout / name
        if not path.is_file():
            raise WarehouseUnavailable(f"missing source member: {name}")
        actual = _sha256(path)
        rows = _csv_rows(path)
        if not allow_drift and actual != pin.sha256:
            mismatches.append(f"{name}: expected {pin.sha256}, got {actual}")
        members[name] = MemberPin(name=name, rows=rows, sha256=actual)
    if mismatches:
        raise ConfigError(
            "source member SHA-256 mismatch (use --allow-checksum-drift after a manual review): "
            + "; ".join(mismatches)
        )
    return members


def _transform(context: _BuildContext) -> None:
    con = context.connection
    src = context.source_dir
    con.execute(f"CREATE TEMP TABLE main_raw AS SELECT * FROM {_read_csv(src / 'main.csv')}")
    con.execute(f"CREATE TEMP TABLE awards_raw AS SELECT * FROM {_read_csv(src / 'awards.csv')}")
    con.execute(
        "CREATE TEMP TABLE awards_suppliers_raw AS SELECT * FROM "
        f"{_read_csv(src / 'awards_suppliers.csv')}"
    )
    con.execute(
        f"CREATE TEMP TABLE contracts_raw AS SELECT * FROM {_read_csv(src / 'contracts.csv')}"
    )
    con.execute(f"CREATE TEMP TABLE parties_raw AS SELECT * FROM {_read_csv(src / 'parties.csv')}")
    con.execute(
        f"CREATE TEMP TABLE items_raw AS SELECT * FROM {_read_csv(src / 'tender_items.csv')}"
    )

    bad_currency = con.execute(
        "SELECT COUNT(*) FROM main_raw WHERE tender_status IS NOT NULL "
        "AND tender_value_currency IS NOT NULL AND tender_value_currency <> 'USD'"
    ).fetchone()
    if bad_currency and bad_currency[0]:
        raise ConfigError(f"unexpected tender currency rows: {bad_currency[0]}")

    # (a) tenders: only releases with a tender status (drops planning-only rows).
    con.execute(
        f"""
        CREATE TEMP TABLE tenders AS
        SELECT
            ocid AS tender_id,
            regexp_extract(ocid, '^[^-]+-[^-]+-([^-]+-[^-]+)', 1) AS process_code,
            TRY_CAST(LEFT(date, 10) AS DATE) AS release_date,
            regexp_extract(buyer_id, 'EC-RUC-([0-9]{{13}})', 1) AS buyer_id,
            {_collapse("tender_title")} AS title,
            LEFT({_collapse("tender_description")}, 240) AS description,
            NULLIF({_collapse("tender_procurementMethod")}, '') AS procurement_method,
            CASE
                WHEN {_collapse("tender_procurementMethodDetails")} ILIKE 'Catálogo electrónico%'
                    THEN 'catalogo_electronico'
                WHEN {_collapse("tender_procurementMethodDetails")} = 'Subasta Inversa Electrónica'
                    THEN 'subasta_inversa'
                WHEN {_collapse("tender_procurementMethodDetails")} = 'Menor Cuantía'
                    THEN 'menor_cuantia'
                WHEN {_collapse("tender_procurementMethodDetails")} = 'Cotización'
                    THEN 'cotizacion'
                WHEN {_collapse("tender_procurementMethodDetails")} IN (
                    'Contratacion directa',
                    'Comunicación Social – Contratación Directa',
                    'Bienes y Servicios únicos'
                ) THEN 'contratacion_directa'
                WHEN {_collapse("tender_procurementMethodDetails")} =
                    'Contratos entre Entidades Públicas o sus subsidiarias'
                    THEN 'entre_entidades_publicas'
                ELSE 'otros'
            END AS procurement_type,
            {_collapse("tender_procurementMethodDetails")} AS method_details,
            NULLIF({_collapse("tender_mainProcurementCategory")}, '') AS category,
            {_collapse("tender_status")} AS status,
            TRY_CAST(tender_value_amount AS DOUBLE) AS planned_amount_usd,
            TRY_CAST(tender_numberOfTenderers AS INTEGER) AS number_of_tenderers,
            (tender_competitive = 'true') AS is_competitive
        FROM main_raw
        WHERE tender_status IS NOT NULL
        ORDER BY tender_id
        """
    )

    # (b) buyers: distinct buyer ids of retained tenders plus party geography.
    con.execute(
        f"""
        CREATE TEMP TABLE buyers AS
        WITH names AS (
            SELECT regexp_extract(buyer_id, 'EC-RUC-([0-9]{{13}})', 1) AS buyer_id,
                   MIN({_collapse("buyer_name")}) AS buyer_name
            FROM main_raw
            WHERE tender_status IS NOT NULL
            GROUP BY 1
        )
        SELECT n.buyer_id, n.buyer_name,
               MIN({_collapse("p.address_region")}) AS province,
               MIN({_collapse("p.address_locality")}) AS canton
        FROM names n
        LEFT JOIN parties_raw p
          ON p.id LIKE 'EC-RUC-' || n.buyer_id || '-%' AND p.roles LIKE '%buyer%'
        GROUP BY n.buyer_id, n.buyer_name
        ORDER BY n.buyer_id
        """
    )

    # (c) suppliers: RUC-normalised ids; non-RUC legacy identifiers are folded
    # into one 'other' supplier so the pinned 10,217-row contract holds and no
    # unverifiable personal identifier is published.
    con.execute(
        """
        CREATE TEMP TABLE supplier_raw AS
        SELECT s.id AS raw_id,
               regexp_extract(s.id, 'EC-RUC-([0-9]{13})', 1) AS ruc,
               s.name AS source_name
        FROM awards_suppliers_raw s
        JOIN awards_raw a ON a.main_ocid = s.main_ocid AND a.id = s.awards_id
        JOIN main_raw m ON m.ocid = a.main_ocid
        WHERE m.tender_status IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE supplier_ids AS
        SELECT raw_id, ruc, MIN(source_name) AS source_name
        FROM supplier_raw
        GROUP BY raw_id, ruc
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE supplier_norm AS
        SELECT
            CASE WHEN sr.ruc = '' THEN 'ID-UNKNOWN' ELSE sr.ruc END AS raw_key,
            CASE
                WHEN sr.ruc = '' THEN 'other'
                WHEN SUBSTR(sr.ruc, 3, 1) BETWEEN '0' AND '5' THEN 'natural_person'
                WHEN SUBSTR(sr.ruc, 3, 1) = '6' THEN 'public_entity'
                WHEN SUBSTR(sr.ruc, 3, 1) = '9' THEN 'company'
                ELSE 'other'
            END AS supplier_kind,
            CASE WHEN sr.ruc = '' THEN 'Proveedor no identificado (sin RUC)'
                 ELSE MIN({_collapse("sr.source_name")}) END AS supplier_name,
            CASE WHEN sr.ruc = '' THEN NULL
                 ELSE MIN({_collapse("p.address_region")}) END AS province,
            CASE WHEN sr.ruc = '' THEN NULL
                 ELSE MIN({_collapse("p.address_locality")}) END AS canton
        FROM supplier_ids sr
        LEFT JOIN parties_raw p ON p.id = sr.raw_id
        GROUP BY sr.ruc
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE supplier_stage AS
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY raw_key) AS rn
            FROM supplier_norm WHERE supplier_kind = 'natural_person'
        )
        SELECT
            CASE WHEN n.supplier_kind = 'natural_person'
                 THEN 'PN-' || LPAD(CAST(r.rn AS VARCHAR), 6, '0')
                 ELSE n.raw_key END AS supplier_id,
            CASE WHEN n.supplier_kind = 'natural_person'
                 THEN 'Persona natural PN-' || LPAD(CAST(r.rn AS VARCHAR), 6, '0')
                 ELSE n.supplier_name END AS supplier_name,
            n.supplier_kind, n.province, n.canton, n.raw_key
        FROM supplier_norm n
        LEFT JOIN ranked r ON r.raw_key = n.raw_key
        """
    )
    con.execute(
        "CREATE TEMP TABLE supplier_map AS "
        "SELECT DISTINCT raw_id, supplier_id FROM supplier_raw sr JOIN supplier_stage ss "
        "ON ss.raw_key = CASE WHEN sr.ruc = '' THEN 'ID-UNKNOWN' ELSE sr.ruc END"
    )
    con.execute(
        "CREATE TEMP TABLE suppliers AS SELECT supplier_id, supplier_name, supplier_kind, "
        "province, canton FROM supplier_stage ORDER BY supplier_id"
    )

    # (d) awards of retained tenders.
    con.execute(
        """
        CREATE TEMP TABLE awards AS
        SELECT m.ocid AS tender_id,
               a.id AS award_id,
               sm.supplier_id AS supplier_id,
               TRY_CAST(a.value_amount AS DOUBLE) AS amount_usd,
               NULLIF(regexp_replace(trim(a.status), '[[:space:]]+', ' ', 'g'), '') AS status
        FROM awards_raw a
        JOIN main_raw m ON m.ocid = a.main_ocid AND m.tender_status IS NOT NULL
        JOIN awards_suppliers_raw s ON s.main_ocid = a.main_ocid AND s.awards_id = a.id
        JOIN supplier_map sm ON sm.raw_id = s.id
        ORDER BY tender_id, award_id
        """
    )

    # (e) contracts of retained tenders, deduplicated over the projected columns.
    con.execute(
        f"""
        CREATE TEMP TABLE contracts AS
        SELECT DISTINCT
            c.id AS contract_id,
            m.ocid AS tender_id,
            NULLIF({_collapse("c.awardID")}, '') AS award_id,
            {_collapse("c.status")} AS status,
            TRY_CAST(c.value_amount AS DOUBLE) AS amount_usd,
            TRY_CAST(LEFT(c.dateSigned, 10) AS DATE) AS signed_date,
            TRY_CAST(c.period_durationInDays AS INTEGER) AS duration_days
        FROM contracts_raw c
        JOIN main_raw m ON m.ocid = c.main_ocid AND m.tender_status IS NOT NULL
        ORDER BY contract_id
        """
    )

    # (f) items of retained tenders.
    con.execute(
        f"""
        CREATE TEMP TABLE tender_items AS
        SELECT
            i.id AS item_id,
            m.ocid AS tender_id,
            LEFT({_collapse("i.description")}, 160) AS description,
            TRY_CAST(i.quantity AS DOUBLE) AS quantity,
            NULLIF({_collapse("i.unit_name")}, '') AS unit_name,
            TRY_CAST(i.unit_value_amount AS DOUBLE) AS unit_price_usd,
            NULLIF({_collapse("i.classification_id")}, '') AS cpc_code,
            LEFT(NULLIF({_collapse("i.classification_description")}, ''), 120) AS cpc_description
        FROM items_raw i
        JOIN main_raw m ON m.ocid = i.main_ocid AND m.tender_status IS NOT NULL
        ORDER BY item_id
        """
    )


def _write_parquet(con: duckdb.DuckDBPyConnection, out_dir: Path) -> None:
    for table in TABLE_ORDER:
        key = ", ".join(KEY_COLUMNS[table])
        target = out_dir / f"{table}.parquet"
        con.execute(
            f"COPY (SELECT * FROM {table} ORDER BY {key}) TO {_literal(target)} "
            "(FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 19)"
        )


def _fingerprint(con: duckdb.DuckDBPyConnection, table: str, file: Path) -> dict[str, int | None]:
    amount_column = AMOUNT_COLUMNS[table]
    if amount_column is None:
        sum_cents: int | None = None
    else:
        row = con.execute(
            f"SELECT CASE WHEN COUNT({amount_column}) = 0 THEN NULL "
            f"ELSE CAST(ROUND(SUM({amount_column}) * 100) AS BIGINT) END "
            f"FROM read_parquet({_literal(file)})"
        ).fetchone()
        sum_cents = None if row is None else row[0]
    key = ", ".join(KEY_COLUMNS[table])
    row = con.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT {key} FROM read_parquet({_literal(file)}))"
    ).fetchone()
    return {"sum_amount_cents": sum_cents, "distinct_keys": int(row[0]) if row else 0}


def _built_at() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_manifest(
    con: duckdb.DuckDBPyConnection,
    out_dir: Path,
    members: Mapping[str, MemberPin],
    *,
    built_at: str | None = None,
) -> tuple[dict[str, Any], str]:
    tables: dict[str, object] = {}
    for table in TABLE_ORDER:
        file = out_dir / f"{table}.parquet"
        rows = con.execute(f"SELECT COUNT(*) FROM read_parquet({_literal(file)})").fetchone()
        tables[table] = {
            "file": file.name,
            "sha256": _sha256(file),
            "rows": int(rows[0]) if rows else 0,
            "fingerprint": _fingerprint(con, table, file),
        }
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA,
        "source": {
            "url": SOURCE_PINS.url,
            "year": SOURCE_PINS.year,
            "tarball_sha256": SOURCE_PINS.tarball_sha256,
            "members": {
                name: {"name": pin.name, "sha256": pin.sha256, "rows": pin.rows}
                for name, pin in members.items()
            },
        },
        "tables": tables,
        "tools": {
            "duckdb": duckdb.__version__,
            "sqlagent": __version__,
        },
        "built_at": built_at or _built_at(),
    }
    manifest["tools"]["sqlglot"] = _package_version("sqlglot")
    payload = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    path = out_dir / MANIFEST_NAME
    path.write_text(payload, encoding="utf-8")
    return manifest, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_warehouse(
    source_dir: Path,
    out_dir: Path,
    *,
    allow_drift: bool = False,
    built_at: str | None = None,
) -> BuildReport:
    """Build the six Parquet tables and ``MANIFEST.json`` from an OCDS CSV tree."""

    source_dir = Path(source_dir).resolve()
    out_dir = Path(out_dir).resolve()
    members = check_source_members(source_dir, allow_drift=allow_drift)
    layout = _source_layout(source_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    try:
        con.execute("SET threads=1")
        con.execute("SET preserve_insertion_order=false")
        context = _BuildContext(connection=con, source_dir=layout)
        _transform(context)
        _write_parquet(con, out_dir)
        manifest, manifest_sha = _write_manifest(con, out_dir, members, built_at=built_at)
        table_rows = {table: int(entry["rows"]) for table, entry in manifest["tables"].items()}
        total_bytes = sum((out_dir / f"{table}.parquet").stat().st_size for table in TABLE_ORDER)
    finally:
        con.close()

    return BuildReport(
        tables=table_rows,
        manifest_path=out_dir / MANIFEST_NAME,
        manifest_sha256=manifest_sha,
        total_bytes=total_bytes,
        source_dir=source_dir,
    )


def load_manifest(bundle_dir: Path = BUNDLE_DIR) -> dict[str, Any]:
    """Load and minimally validate a warehouse manifest."""

    path = Path(bundle_dir) / MANIFEST_NAME
    if not path.is_file():
        raise WarehouseUnavailable(f"warehouse MANIFEST.json is missing in {bundle_dir}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WarehouseUnavailable(f"cannot read warehouse manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise WarehouseUnavailable(
            f"unsupported warehouse manifest schema in {path} (expected {MANIFEST_SCHEMA})"
        )
    if not isinstance(manifest.get("tables"), dict):
        raise WarehouseUnavailable("warehouse manifest has no tables map")
    return manifest


def verify_bundle(bundle_dir: Path = BUNDLE_DIR) -> VerifyReport:
    """Recompute file hashes, row counts and fingerprints from the Parquet files."""

    manifest = load_manifest(bundle_dir)
    bundle_dir = Path(bundle_dir)
    tables_meta = manifest["tables"]
    if not isinstance(tables_meta, dict):  # pragma: no cover - load_manifest validates
        raise WarehouseUnavailable("warehouse manifest tables must be an object")
    errors: list[str] = []
    rows_report: dict[str, int] = {}
    con = duckdb.connect()
    try:
        for table, entry in tables_meta.items():
            if not isinstance(entry, dict):
                errors.append(f"{table}: malformed manifest entry")
                continue
            file = bundle_dir / str(entry.get("file", f"{table}.parquet"))
            if not file.is_file():
                errors.append(f"{table}: missing {file.name}")
                continue
            digest = _sha256(file)
            if digest != entry.get("sha256"):
                errors.append(f"{table}: {file.name} SHA-256 mismatch")
                continue
            try:
                row = con.execute(f"SELECT COUNT(*) FROM read_parquet({_literal(file)})").fetchone()
                rows = int(row[0]) if row else 0
                if rows != entry.get("rows"):
                    errors.append(f"{table}: row count {rows} != manifest {entry.get('rows')}")
                    continue
                fingerprint = _fingerprint(con, table, file)
                if fingerprint != entry.get("fingerprint"):
                    errors.append(f"{table}: fingerprint mismatch")
                    continue
                rows_report[table] = rows
            except duckdb.Error as exc:
                errors.append(f"{table}: cannot read {file.name}: {str(exc).splitlines()[0]}")
    finally:
        con.close()
    return VerifyReport(ok=not errors, tables=rows_report, errors=tuple(errors))


def _safe_extract(tarball: Path, destination: Path, *, allow_drift: bool = False) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    mismatches: list[str] = []
    try:
        with tarfile.open(tarball, mode="r:gz") as archive:
            members = {
                posixpath.basename(member.name): member
                for member in archive.getmembers()
                if member.isfile()
            }
            for name, pin in SOURCE_PINS.members.items():
                member = members.get(name)
                if member is None:
                    raise WarehouseUnavailable(f"tarball does not contain {name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise WarehouseUnavailable(f"cannot read {name} from the tarball")
                payload = extracted.read()
                actual = hashlib.sha256(payload).hexdigest()
                if not allow_drift and actual != pin.sha256:
                    mismatches.append(f"{name}: expected {pin.sha256}, got {actual}")
                (destination / name).write_bytes(payload)
    except (tarfile.TarError, OSError) as exc:
        raise WarehouseUnavailable(f"downloaded artefact is not a gzip tar: {exc}") from exc
    if mismatches:
        raise ConfigError(
            "source member SHA-256 mismatch (use --allow-checksum-drift after a manual review): "
            + "; ".join(mismatches)
        )
    return destination


def download_source(
    year: int = SOURCE_PINS.year,
    cache_dir: Path | None = None,
    *,
    allow_drift: bool = False,
    client: httpx.Client | None = None,
    timeout_s: float = 120.0,
) -> Path:
    """Download the pinned OCDS tarball, verify it and extract the six members.

    This is the only function in the package that needs the network.  Member
    hashes are the pin (the tarball is regenerated monthly); a mismatch is
    retried once and then either allowed with ``allow_drift`` or rejected.
    """

    if year != SOURCE_PINS.year:
        raise ConfigError(f"only the {SOURCE_PINS.year} OCDS publication is pinned")
    cache = Path(cache_dir or Path.cwd() / ".sqlagent-cache") / str(year)
    cache.mkdir(parents=True, exist_ok=True)
    tarball = cache / f"{year}.csv.tar.gz"
    extracted = cache / "csv"
    owned_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout_s)
    try:
        attempts = 2
        for attempt in range(attempts):
            if attempt or not tarball.is_file():
                _download_tarball(http, tarball)
            try:
                return _safe_extract(tarball, extracted, allow_drift=allow_drift)
            except ConfigError:
                if attempt + 1 >= attempts:
                    raise
                tarball.unlink(missing_ok=True)
        raise AssertionError("unreachable")  # pragma: no cover - loop always returns/raises
    finally:
        if owned_client:
            http.close()


def _download_tarball(client: httpx.Client, target: Path) -> None:
    tmp = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    try:
        with client.stream("GET", SOURCE_PINS.url) as response:
            response.raise_for_status()
            with tmp.open("wb") as handle:
                for chunk in response.iter_bytes():
                    digest.update(chunk)
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise WarehouseUnavailable(f"cannot download the OCDS source: {exc}") from exc
    tmp.replace(target)
    # The tarball hash is informational: D6 pins the six members because the
    # upstream archive is regenerated monthly.
    (target.parent / "tarball.sha256").write_text(digest.hexdigest() + "\n", encoding="utf-8")


def download_and_build(
    out_dir: Path,
    *,
    year: int = SOURCE_PINS.year,
    cache_dir: Path | None = None,
    allow_drift: bool = False,
) -> BuildReport:
    """Convenience composition used by ``sqlagent data build``."""

    source = download_source(year, cache_dir, allow_drift=allow_drift)
    return build_warehouse(source, out_dir, allow_drift=allow_drift)


__all__ = [
    "ATTRIBUTION",
    "BUNDLE_DIR",
    "LICENSE",
    "MANIFEST_SCHEMA",
    "SOURCE_PINS",
    "BuildReport",
    "MemberPin",
    "SourcePins",
    "VerifyReport",
    "build_warehouse",
    "check_source_members",
    "download_and_build",
    "download_source",
    "load_manifest",
    "verify_bundle",
]
