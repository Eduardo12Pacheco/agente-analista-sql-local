# ADR-0008: Parquet bundle and materialised DuckDB warehouse

## Context

The application must start offline on Linux, Windows and macOS, expose a
read-only analytical warehouse to the agent, and stay small enough to ship in a
wheel. Options included a CSV bundle, a prebuilt `.duckdb` file, or Parquet plus
an on-first-use materialisation step. A prebuilt DuckDB file is storage-format
specific and would be rewritten by DuckDB upgrades; CSV is bulky, slow and
loses types. The agent must never hold a writable connection.

## Decision

Ship six Parquet files (zstd level 19) plus `MANIFEST.json` in
`src/sqlagent/resources/warehouse/`. At first use, `ensure_warehouse(settings)`
materialises them into
`<data_dir>/warehouse-<manifest-sha8>.duckdb` with declared primary and foreign
keys. The filename embeds the manifest hash, so a rebuilt bundle yields a fresh
database while an existing one is reused with no migration.

Materialisation is atomic: the database is created in a temporary file in the
same directory and `os.replace`d into place only after all tables and
constraints exist. The connection used by the agent is then opened with
`read_only=True`; the materialiser is the only writer. The manifest stores file
hashes, row counts, monetary fingerprints and distinct-key counts so
`sqlagent data verify` can detect a stale or corrupted bundle.

## Consequences

* The wheel stays below the size budget and is portable across DuckDB versions.
* First use costs one materialisation (measured about 2–5 s on the reference
  machine, asserted at ≤ 30 s in tests); later starts reuse the file.
* A bundle change invalidates only the derived database, not user data.
* Any process that can write the user data directory can tamper with the
  materialised file; the agent still opens it read-only and applies the D15
  lockdown, and `data verify` can rebuild from the committed Parquet.
* DuckDB constraints are declared but foreign keys are not enforced during
  insert; an integration test checks for orphans instead.

## Alternatives considered

* **Prebuilt `.duckdb` in the wheel** — largest artifact, tied to a DuckDB
  storage version, harder to inspect or verify in git; rejected.
* **CSV bundle read on every start** — no binary artifact, but slow, no types
  and roughly an order of magnitude larger; rejected.
* **SQLite** — widely available but weaker analytical SQL (windows, date_trunc,
  list functions) and no native Parquet reader; rejected.
* **Materialise into the package directory** — breaks read-only installs and
  pollutes site-packages; rejected.
* **Non-versioned database filename** — would require detecting bundle changes
  on every start or silently serving stale data; rejected.
