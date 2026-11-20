# ruff: noqa: S608
"""External lakehouse manifest adapter (S31/D28).

A manifest is untrusted configuration: it is validated by a pydantic model,
its DuckDB file is verified against a SHA-256 digest, and the database is opened
through the same locked, read-only :class:`DuckDbWarehouse` used for the bundled
bundle.  The manifest is the single source of truth for the table allowlist and
the semantic layer of an external warehouse.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal

import duckdb
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from sqlagent.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from sqlagent.application.ports import Catalog, WarehouseInfo, WarehouseLimits
from sqlagent.domain.errors import ConfigError, QueryTimeoutError, WarehouseUnavailable
from sqlagent.domain.models import ColumnInfo, QueryResult
from sqlagent.domain.sql_policy import ValidatedQuery

LAKEHOUSE_SCHEMA = "sqlagent.lakehouse-manifest/v1"

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_RESERVED_TABLES = frozenset({"information_schema", "sqlite_master"})
_RESERVED_PREFIXES = ("duckdb_", "pg_")

_MANIFEST_CONFIG = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _non_blank(value: str, where: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{where} must be a non-empty string")
    return value.strip()


def _identifier(value: str, where: str) -> str:
    value = _non_blank(value, where)
    if not _IDENTIFIER.match(value):
        raise ValueError(f"{where} must be a SQL identifier, got {value!r}")
    return value


def _reject_system_table(name: str) -> str:
    lowered = name.casefold()
    if lowered in _RESERVED_TABLES or lowered.startswith(_RESERVED_PREFIXES):
        raise ValueError(f"table {name!r} is a reserved system catalog name")
    return name


class ManifestColumn(BaseModel):
    """One documented column of an external lakehouse table (D28)."""

    model_config = _MANIFEST_CONFIG

    name: str
    type: str
    description: str
    synonyms: tuple[str, ...] = ()
    lookupable: bool = False
    samples: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        return _identifier(value, "column.name")

    @field_validator("type")
    @classmethod
    def _valid_type(cls, value: str) -> str:
        return _non_blank(value, "column.type")

    @field_validator("description")
    @classmethod
    def _valid_description(cls, value: str) -> str:
        return _non_blank(value, "column.description")


class ManifestTable(BaseModel):
    """One documented table of an external lakehouse (D28)."""

    model_config = _MANIFEST_CONFIG

    name: str
    description: str
    columns: tuple[ManifestColumn, ...]

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        return _reject_system_table(_identifier(value, "table.name"))

    @field_validator("description")
    @classmethod
    def _valid_description(cls, value: str) -> str:
        return _non_blank(value, "table.description")

    @field_validator("columns")
    @classmethod
    def _valid_columns(cls, value: tuple[ManifestColumn, ...]) -> tuple[ManifestColumn, ...]:
        if not value:
            raise ValueError("table.columns must not be empty")
        seen: set[str] = set()
        for column in value:
            key = column.name.casefold()
            if key in seen:
                raise ValueError(f"duplicate column: {column.name}")
            seen.add(key)
        return value


class ManifestRelationship(BaseModel):
    """A documented join path between two external columns (D28)."""

    model_config = _MANIFEST_CONFIG

    from_: str = Field(alias="from")
    to: str

    @field_validator("from_", "to")
    @classmethod
    def _valid_reference(cls, value: str) -> str:
        reference = _non_blank(value, "relationship reference")
        table, separator, column = reference.partition(".")
        if not separator or not table or not column or "." in column:
            raise ValueError(f"relationship reference must be table.column, got {reference!r}")
        _identifier(table, "relationship table")
        _identifier(column, "relationship column")
        return reference


class LakehouseManifest(BaseModel):
    """The ``sqlagent.lakehouse-manifest/v1`` contract (D28)."""

    model_config = _MANIFEST_CONFIG

    schema_: Literal["sqlagent.lakehouse-manifest/v1"] = Field(alias="schema")
    name: str
    generated_at: datetime
    duckdb_file: Path
    sha256: str
    tables: tuple[ManifestTable, ...]
    relationships: tuple[ManifestRelationship, ...] = ()
    language: Literal["es", "en", "multi"] = "multi"

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        return _non_blank(value, "name")

    @field_validator("duckdb_file")
    @classmethod
    def _relative_file(cls, value: Path) -> Path:
        raw = str(value)
        windows = PureWindowsPath(raw)
        posix = PurePosixPath(raw)
        if value.is_absolute() or windows.is_absolute() or posix.is_absolute():
            raise ValueError("duckdb_file must be relative to the manifest directory")
        parts = {*windows.parts, *posix.parts, *value.parts}
        if ".." in parts:
            raise ValueError("duckdb_file must not escape the manifest directory")
        return value

    @field_validator("sha256")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        if not _SHA256.match(value):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        return value.lower()

    @field_validator("tables")
    @classmethod
    def _valid_tables(cls, value: tuple[ManifestTable, ...]) -> tuple[ManifestTable, ...]:
        if not value:
            raise ValueError("tables must not be empty")
        seen: set[str] = set()
        for table in value:
            key = table.name.casefold()
            if key in seen:
                raise ValueError(f"duplicate table: {table.name}")
            seen.add(key)
        return value

    @model_validator(mode="after")
    def _valid_relationships(self) -> LakehouseManifest:
        tables = {table.name.casefold(): table for table in self.tables}
        for relationship in self.relationships:
            for reference in (relationship.from_, relationship.to):
                table_name, _, column_name = reference.partition(".")
                table = tables.get(table_name.casefold())
                if table is None:
                    raise ValueError(f"relationship {reference!r} points to an undocumented table")
                if not any(
                    column.name.casefold() == column_name.casefold() for column in table.columns
                ):
                    raise ValueError(f"relationship {reference!r} points to an undocumented column")
        return self


def load_manifest(path: Path) -> LakehouseManifest:
    """Read, parse and validate a manifest; every failure is a ``ConfigError``."""

    manifest_path = Path(path)
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read lakehouse manifest {manifest_path.name}: {exc}") from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"cannot parse lakehouse manifest {manifest_path.name}: {exc}") from exc
    try:
        return LakehouseManifest.model_validate(document)
    except ValidationError as exc:
        raise ConfigError(f"invalid lakehouse manifest {manifest_path.name}: {exc}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_type(value: str) -> str:
    return " ".join(value.upper().split())


class LakehouseWarehouse:
    """A verified, locked and read-only view over an external DuckDB file."""

    def __init__(
        self,
        manifest: LakehouseManifest,
        manifest_path: Path,
        limits: WarehouseLimits | None = None,
    ) -> None:
        self.manifest = manifest
        self.manifest_path = Path(manifest_path).resolve()
        self._base = self.manifest_path.parent
        self.path = (self._base / manifest.duckdb_file).resolve()
        try:
            self.path.relative_to(self._base)
        except ValueError as exc:  # pragma: no cover - manifest validator guards this
            raise ConfigError("duckdb_file must stay inside the manifest directory") from exc
        if not self.path.is_file():
            raise WarehouseUnavailable(f"lakehouse DuckDB file is missing: {self.path}")
        actual = _sha256_file(self.path)
        if actual != manifest.sha256:
            raise WarehouseUnavailable(
                f"lakehouse SHA-256 mismatch: manifest expects {manifest.sha256}, file has {actual}"
            )
        self._inner = DuckDbWarehouse(self.path, limits)
        try:
            self._catalog = self._validate_catalog()
        except Exception:
            self._inner.close()
            raise

    # -- lifecycle -----------------------------------------------------
    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Raw connection, exposed for defence-in-depth tests only."""

        return self._inner.connection

    def close(self) -> None:
        self._inner.close()

    def __enter__(self) -> LakehouseWarehouse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- validation ----------------------------------------------------
    def _validate_catalog(self) -> Catalog:
        actual = self._inner.catalog()
        tables: dict[str, tuple[ColumnInfo, ...]] = {}
        for table in self.manifest.tables:
            columns = actual.tables.get(table.name.casefold())
            if columns is None:
                raise ConfigError(
                    f"lakehouse manifest table {table.name!r} is not in the DuckDB file"
                )
            by_name = {column.name.casefold(): column for column in columns}
            documented: list[ColumnInfo] = []
            for column in table.columns:
                found = by_name.get(column.name.casefold())
                if found is None:
                    raise ConfigError(
                        "lakehouse manifest column "
                        f"{table.name}.{column.name} is not in the DuckDB file"
                    )
                if _normalise_type(found.type) != _normalise_type(column.type):
                    raise ConfigError(
                        "lakehouse manifest column "
                        f"{table.name}.{column.name} declares {column.type!r} "
                        f"but the DuckDB file has {found.type!r}"
                    )
                documented.append(ColumnInfo(name=found.name, type=found.type))
            tables[table.name] = tuple(documented)
        return Catalog(tables=tables)

    # -- WarehousePort -------------------------------------------------
    def catalog(self) -> Catalog:
        return self._catalog

    def execute(self, query: ValidatedQuery) -> QueryResult:
        return self._inner.execute(query)

    def lookup_values(self, ref: str, query: str, k: int = 5) -> list[str]:
        return self._inner.lookup_values(ref, query, k)

    def info(self) -> WarehouseInfo:
        counts: dict[str, int] = {}
        for name in self._catalog.tables:
            try:
                row = self.connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
            except duckdb.Error as exc:  # pragma: no cover - catalog was validated
                raise QueryTimeoutError(f"cannot count rows in {name}: {exc}") from exc
            counts[name] = int(row[0]) if row else 0
        return WarehouseInfo(
            path=self.path,
            manifest_sha256=self.manifest.sha256,
            tables=counts,
            source_url="",
            license="",
            attribution=f"External lakehouse: {self.manifest.name}",
            built_at=self.manifest.generated_at.isoformat(),
        )


def open_lakehouse(
    manifest_path: Path,
    limits: WarehouseLimits | None = None,
) -> LakehouseWarehouse:
    """Load a manifest and open its verified DuckDB file read-only."""

    manifest = load_manifest(manifest_path)
    return LakehouseWarehouse(manifest, manifest_path, limits)


__all__ = [
    "LAKEHOUSE_SCHEMA",
    "LakehouseManifest",
    "LakehouseWarehouse",
    "ManifestColumn",
    "ManifestRelationship",
    "ManifestTable",
    "load_manifest",
    "open_lakehouse",
]
