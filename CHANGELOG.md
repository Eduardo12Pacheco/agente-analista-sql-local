# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-20

First public release: a local-first AI data analyst over a bundled DuckDB warehouse.

### Added

- Agent state machine (`UNDERSTAND → RETRIEVE → GENERATE ⇄ TOOL → VALIDATE →
  EXECUTE → (REPAIR → VALIDATE)* → CHART → NARRATE → DONE`) with bounded tool calls,
  repairs, protocol retries and a 12-call hard cap.
- Bilingual Spanish/English semantic layer and deterministic BM25 retrieval, plus
  fixed-query `lookup_values` for entity resolution.
- Layered SQL guardrails: sqlglot AST policy with parse-don't-validate
  `ValidatedQuery`, prompt-injection-safe data rendering, locked read-only DuckDB,
  row cap, query timeout and memory limits.
- Local Ollama backend with JSON-schema structured outputs, scripted/replay backends
  and record/replay cassettes; no cloud APIs or keys.
- Bundled SERCOP Ecuador OCDS 2021 warehouse: six Parquet tables, pseudonymised
  natural persons, manifest checksums, ETL rebuild command and offline verification.
- Evaluation engine: 72-question benchmark v1, execution accuracy with Wilson
  intervals, per-category/language/difficulty breakdowns, ablations, Markdown/HTML
  reports, baseline regression gate and a recorded-output replay test.
- Local web chat (FastAPI + HTMX + SSE, vendored assets, light/dark, ES/EN) and a
  Typer CLI with `ask`, `eval`, `serve`, `doctor` and `data` commands.
- External lakehouse manifest adapter with SHA-256 verification and read-only
  lockdown.
- CI matrix on Ubuntu/Windows/macOS with lint, types, tests, e2e, eval gate,
  installer smoke and security jobs; tagged releases with changelog and checksums.
- Read-only screenshot and demo-GIF capture from the real app, generated README
  metrics, and complete architecture, data, evaluation, configuration and lakehouse
  documentation with nine ADRs.

### Changed

- Default model is `qwen2.5-coder:7b`, selected by benchmark execution accuracy
  (63.3% on 60 answerable items) over `qwen3:8b` (61.7%).

### Fixed

- Lookup values rank by matched query tokens so colloquial IESS/Guayas queries resolve
  to the canonical public entity and province names.

[0.1.0]: https://github.com/Eduardo12Pacheco/agente-analista-sql-local/releases/tag/v0.1.0
