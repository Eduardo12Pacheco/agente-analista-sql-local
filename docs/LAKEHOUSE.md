# External lakehouse adapter

`sqlagent` normally answers questions over its bundled SERCOP warehouse. With a
**lakehouse manifest** it can instead read a DuckDB file produced by another
local project, with the same locked, read-only connection, SQL policy and agent
loop. The adapter is optional and has no runtime dependency on the producing
project: the manifest is a plain JSON file with a documented, versioned schema.

- Contract: `sqlagent.lakehouse-manifest/v1`
- JSON Schema: [`docs/lakehouse-manifest.schema.json`](lakehouse-manifest.schema.json)
- Example: [`docs/examples/lakehouse-manifest.example.json`](examples/lakehouse-manifest.example.json)

## Quickstart

```bash
# Validate a manifest and inspect its database before asking anything.
sqlagent doctor --offline --manifest /path/to/manifest.json

# Ask over the external warehouse (Ollama or replay; the bundled benchmark does
# not apply to external warehouses).
sqlagent ask --manifest /path/to/manifest.json "How many rows are in the sales table?"

# Or point the web chat at it.
sqlagent serve --manifest /path/to/manifest.json --port 17080
```

The same value can be provided through the environment:

```bash
export SQLAGENT_LAKEHOUSE_MANIFEST=/path/to/manifest.json
sqlagent doctor --offline
```

When `--manifest`/`SQLAGENT_LAKEHOUSE_MANIFEST` is set, it replaces the bundled
Parquet bundle entirely. Exit codes are the usual ones: `2` for an invalid
configuration/manifest, `3` for a missing or tampered DuckDB file or an
environment problem, `0` on success.

## Manifest fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema` | string | yes | Exactly `sqlagent.lakehouse-manifest/v1`. |
| `name` | string | yes | Human-readable lakehouse name, shown by `doctor`. |
| `generated_at` | ISO-8601 date-time | yes | When the DB/manifest pair was produced. |
| `duckdb_file` | relative path | yes | DuckDB file, relative to the manifest directory. Absolute paths and `..` escapes are rejected. |
| `sha256` | 64 hex chars | yes | SHA-256 of `duckdb_file`; verified before the file is opened. |
| `tables` | array (≥ 1) | yes | Documented tables, in prompt order. |
| `tables[].name` | SQL identifier | yes | Table name in the DuckDB file. |
| `tables[].description` | string | yes | One-line description used in EN and ES prompts. |
| `tables[].columns` | array (≥ 1) | yes | Documented columns. |
| `tables[].columns[].name` | SQL identifier | yes | Column name. |
| `tables[].columns[].type` | string | yes | DuckDB type, e.g. `VARCHAR`, `BIGINT`, `DOUBLE`, `DATE`. |
| `tables[].columns[].description` | string | yes | One-line description used in EN and ES prompts. |
| `tables[].columns[].synonyms` | string array | no | Bilingual retrieval terms (default empty). |
| `tables[].columns[].lookupable` | boolean | no | Allow `lookup_values` on this text column (default `false`). |
| `tables[].columns[].samples` | string array | no | Low-cardinality sample values for retrieval. |
| `relationships` | array | no | Join paths as `{"from": "table.column", "to": "table.column"}`. |
| `language` | `es`, `en`, `multi` | no | Documentation language hint (default `multi`). |

The manifest is the **only** schema source for an external warehouse: metrics,
glossary entries and few-shot examples from the bundled resources are disabled,
because the contract does not carry them.

## How a sibling project emits a manifest

1. Write the DuckDB file deterministically (fixed ordering, no timestamps) and
   close all connections.
2. Hash it with a tool available on Linux, macOS and Windows. On Linux/macOS:

   ```bash
   sha256sum warehouse/lakehouse.duckdb
   ```

   On Windows PowerShell:

   ```powershell
   (Get-FileHash -Algorithm SHA256 warehouse\lakehouse.duckdb).Hash.ToLower()
   ```

   Or from Python, cross-platform:

   ```bash
   python -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('warehouse/lakehouse.duckdb').read_bytes()).hexdigest())"
   ```

3. Generate the JSON file (the example below is also committed as
   `docs/examples/lakehouse-manifest.example.json`):

   ```json
   {
     "schema": "sqlagent.lakehouse-manifest/v1",
     "name": "example-lakehouse",
     "generated_at": "2026-11-20T12:00:00Z",
     "duckdb_file": "example.duckdb",
     "sha256": "<sha256 of example.duckdb>",
     "tables": [
       {
         "name": "countries",
         "description": "Countries with their region.",
         "columns": [
           {
             "name": "country_code",
             "type": "VARCHAR",
             "description": "ISO 3166-1 alpha-3 country code.",
             "synonyms": ["pais", "codigo de pais"],
             "lookupable": true,
             "samples": ["ECU", "PER"]
           }
         ]
       }
     ],
     "relationships": [],
     "language": "en"
   }
   ```

4. Validate the manifest locally before publishing it: `sqlagent doctor
   --offline --manifest <path>` prints the manifest name and table count, then
   opens the database read-only and reports row counts. The bundled test suite
   validates the committed example and the JSON Schema on every run.

No other repository is imported at runtime; integration is only through this
documented artifact. The producer and the consumer can evolve independently as
long as the `v1` contract is respected.

## Validation and security

Before any query runs, the adapter checks:

- JSON syntax and the `sqlagent.lakehouse-manifest/v1` schema (pydantic model,
  `extra="forbid"`), with readable `ConfigError` messages;
- `duckdb_file` is relative, does not escape the manifest directory and exists;
- the file SHA-256 equals `sha256`; a mismatch aborts with
  `lakehouse SHA-256 mismatch: manifest expects …, file has …` and CLI exit 3;
- no table uses a reserved system name (`information_schema`, `sqlite_master`,
  or any `duckdb_*` / `pg_*` catalog name);
- every documented table exists in the file, and every documented column exists
  with the declared type (missing/typed-differently columns are rejected);
- the manifest table allowlist becomes the `SqlPolicy` table allowlist, so SQL
  cannot reach undocumented tables.

The database is then opened exactly like the bundled warehouse:
`read_only=True`, extension autoload/autoinstall disabled, external access off,
memory/thread limits applied and `lock_configuration=true` last. `sqlagent
doctor` also honours `--manifest`, so an invalid or tampered artifact is caught
before the agent starts.

## Limitations

- The benchmark (`sqlagent eval`) is defined only for the bundled SERCOP
  warehouse; it is not scored against external data.
- External warehouses have no metrics, glossary or few-shot examples, so
  retrieval and narration rely on the manifest descriptions only.
- The manifest describes a DuckDB file, not a live database server; the file
  must be local and stable while a run is in progress.
- Only the documented columns are documented in prompts; undocumented columns
  in the file are rejected by the SQL policy even if they physically exist.
