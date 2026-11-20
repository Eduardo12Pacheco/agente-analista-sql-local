# ruff: noqa: S608
"""Read-only, locked-down DuckDB implementation of ``WarehousePort`` (S15/S17).

Defence in depth is explicit here: the connection is opened ``read_only=True``,
extension loading and filesystem access are disabled, resource limits are set,
and ``lock_configuration`` freezes the configuration last (D15).  Every query
comes from ``ValidatedQuery`` and is bounded by a row cap plus a watchdog timer.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from pathlib import Path
from typing import Any

import duckdb

from sqlagent.adapters.warehouse.etl import (
    ATTRIBUTION,
    LICENSE,
    MANIFEST_NAME,
    SOURCE_PINS,
    load_manifest,
)
from sqlagent.application.ports import Catalog, WarehouseInfo, WarehouseLimits
from sqlagent.domain.errors import (
    QueryTimeoutError,
    SqlExecutionError,
    WarehouseUnavailable,
)
from sqlagent.domain.models import ColumnInfo, QueryResult
from sqlagent.domain.sql_policy import ValidatedQuery

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TEXT_TYPES = ("VARCHAR", "TEXT", "STRING")

_LOCKDOWN: tuple[str, ...] = (
    # Extension controls first.
    "SET autoload_known_extensions=false",
    "SET autoinstall_known_extensions=false",
    "SET allow_community_extensions=false",
    "SET allow_unsigned_extensions=false",
    # No filesystem paths are reachable once external access is off.
    "SET allowed_paths=[]",
    # Resource limits.
    "SET memory_limit='{memory_limit}'",
    "SET threads={threads}",
    # File/network access off, then freeze the configuration.
    "SET enable_external_access=false",
    "SET lock_configuration=true",
)


class DuckDbWarehouse:
    """A single read-only connection with a watchdog-protected ``execute``."""

    def __init__(
        self,
        path: Path,
        limits: WarehouseLimits | None = None,
        *,
        manifest_path: Path | None = None,
    ) -> None:
        self.path = Path(path)
        self.limits = limits or WarehouseLimits()
        self.manifest_path = Path(manifest_path) if manifest_path is not None else None
        if not self.path.is_file():
            raise WarehouseUnavailable(f"warehouse file is missing: {self.path}")
        try:
            self._connection = duckdb.connect(str(self.path), read_only=True)
        except duckdb.Error as exc:
            raise WarehouseUnavailable(f"cannot open the warehouse read-only: {exc}") from exc
        self._lock = threading.Lock()
        self._closed = False
        self._manifest: dict[str, Any] | None = None
        try:
            self._catalog = self._load_catalog()
            self._apply_lockdown()
            if self.manifest_path is not None:
                self._manifest = load_manifest(self.manifest_path.parent)
        except Exception:
            self._connection.close()
            raise

    # -- lifecycle -----------------------------------------------------
    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Raw connection, exposed for defence-in-depth tests only."""

        return self._connection

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> DuckDbWarehouse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- setup ---------------------------------------------------------
    def _load_catalog(self) -> Catalog:
        rows = self._connection.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position"
        ).fetchall()
        grouped: dict[str, list[ColumnInfo]] = {}
        for table, column, data_type in rows:
            grouped.setdefault(str(table), []).append(
                ColumnInfo(name=str(column), type=str(data_type))
            )
        return Catalog(tables={name: tuple(columns) for name, columns in grouped.items()})

    def _apply_lockdown(self) -> None:
        try:
            for statement in _LOCKDOWN:
                self._connection.execute(
                    statement.format(
                        memory_limit=self.limits.memory_limit,
                        threads=int(self.limits.threads),
                    )
                )
        except duckdb.Error as exc:
            self._connection.close()
            raise WarehouseUnavailable(f"cannot lock down the warehouse: {exc}") from exc

    # -- WarehousePort -------------------------------------------------
    def catalog(self) -> Catalog:
        return self._catalog

    def execute(self, query: ValidatedQuery) -> QueryResult:
        if not isinstance(query, ValidatedQuery):
            raise TypeError("execute() accepts only a ValidatedQuery")
        interrupted = threading.Event()

        def _interrupt() -> None:
            interrupted.set()
            self._connection.interrupt()

        timer = threading.Timer(self.limits.query_timeout_s, _interrupt)
        timer.daemon = True
        started = time.perf_counter()
        with self._lock:
            timer.start()
            try:
                cursor = self._connection.execute(query.sql)
                fetched = cursor.fetchmany(self.limits.max_rows + 1)
                columns = tuple(
                    ColumnInfo(name=str(description[0]), type=str(description[1]))
                    for description in cursor.description or ()
                )
            except duckdb.Error as exc:
                if interrupted.is_set():
                    raise QueryTimeoutError(
                        f"query exceeded {self.limits.query_timeout_s:g}s and was interrupted"
                    ) from exc
                message = str(exc).strip()
                raise SqlExecutionError(message[:300]) from exc
            finally:
                timer.cancel()
        elapsed_ms = (time.perf_counter() - started) * 1000
        truncated = len(fetched) > self.limits.max_rows
        rows = tuple(tuple(row) for row in fetched[: self.limits.max_rows])
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            elapsed_ms=round(elapsed_ms, 3),
        )

    def _resolve_text_column(self, ref: str) -> tuple[str, str]:
        table, _, column = ref.partition(".")
        if not table or not column or "." in column:
            raise ValueError(f"invalid column reference: {ref!r}")
        if not _IDENTIFIER.match(table) or not _IDENTIFIER.match(column):
            raise ValueError(f"invalid column reference: {ref!r}")
        table_name = table.lower()
        columns = self._catalog.tables.get(table_name)
        if columns is None:
            raise ValueError(f"table {table!r} is not in the catalog")
        match = next((item for item in columns if item.name.lower() == column.lower()), None)
        if match is None:
            raise ValueError(f"column {ref!r} is not in the catalog")
        if not match.type.upper().startswith(_TEXT_TYPES):
            raise ValueError(f"column {ref!r} is not a text column")
        return table_name, match.name

    def lookup_values(self, ref: str, query: str, k: int = 5) -> list[str]:
        if k < 1:
            return []
        table, column = self._resolve_text_column(ref)
        limit = min(k, 5)
        tokens = [token for token in re.split(r"[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", query) if token]
        if not tokens:
            return []
        folded = f'LOWER(strip_accents(CAST("{column}" AS VARCHAR)))'
        words = f"string_split({folded}, ' ')"
        acronym = (
            "array_to_string(list_transform(list_filter("
            f"{words}, lambda word: LENGTH(word) > 2), lambda word: LEFT(word, 1)), '')"
        )
        # The token list is bound once through a VALUES relation; scoring counts
        # matched tokens ("IESS seguridad social" ranks the institution above
        # IESS hospitals) with Jaro-Winkler as a small tie-breaker.
        values = ", ".join(["(?)"] * len(tokens))
        matches = f"contains({folded}, token) OR {acronym} = token"
        sql = (
            "SELECT value FROM ("
            f'SELECT CAST("{column}" AS VARCHAR) AS value, '
            f"SUM(CASE WHEN {matches} THEN 1 ELSE 0 END) "
            f"+ 0.01 * MAX(jaro_winkler_similarity({folded}, token)) AS score "
            f'FROM "{table}" CROSS JOIN (VALUES {values}) AS tokens(token) '
            f'WHERE "{column}" IS NOT NULL '
            "GROUP BY value HAVING SUM(CASE WHEN "
            f"{matches} THEN 1 ELSE 0 END) > 0"
            ") ORDER BY score DESC, value LIMIT ?"
        )
        parameters = [*tokens, limit]
        with self._lock:
            try:
                rows = self._connection.execute(sql, parameters).fetchall()
            except duckdb.Error as exc:
                raise SqlExecutionError(str(exc).strip()[:300]) from exc
        return [str(row[0]) for row in rows]

    def info(self) -> WarehouseInfo:
        if self._manifest is None:
            counts = dict.fromkeys(self._catalog.tables, 0)
            with self._lock:
                for name in counts:
                    row = self._connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
                    counts[name] = int(row[0]) if row else 0
            return WarehouseInfo(
                path=self.path,
                manifest_sha256="",
                tables=counts,
                source_url=SOURCE_PINS.url,
                license=LICENSE,
                attribution=ATTRIBUTION,
            )
        manifest_path = self.manifest_path or (self.path.parent / MANIFEST_NAME)
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        tables_meta = self._manifest.get("tables", {})
        if not isinstance(tables_meta, dict):  # pragma: no cover - load_manifest validates
            raise WarehouseUnavailable("warehouse manifest tables must be an object")
        counts = {
            name: int(entry.get("rows", 0))
            for name, entry in tables_meta.items()
            if isinstance(entry, dict)
        }
        source = self._manifest.get("source", {})
        if not isinstance(source, dict):  # pragma: no cover - load_manifest validates
            source = {}
        return WarehouseInfo(
            path=self.path,
            manifest_sha256=digest,
            tables=counts,
            source_url=str(source.get("url", SOURCE_PINS.url)),
            license=LICENSE,
            attribution=ATTRIBUTION,
            built_at=(
                str(self._manifest.get("built_at")) if self._manifest.get("built_at") else None
            ),
        )


__all__ = ["DuckDbWarehouse"]
