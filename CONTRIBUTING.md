# Contributing

Thanks for your interest in `local-sql-analyst-agent`. This document describes the
local workflow and the quality gates every change must pass.

## Setup

Prerequisites: Python 3.12 and [uv](https://docs.astral.sh/uv/) (no Docker or Ollama is
needed for the default test suite).

```bash
uv sync
uv run pytest -m "not e2e"
```

## Commands

| Command | Purpose |
|---|---|
| `make install` | Synchronise the environment from `uv.lock`. |
| `make lint` | `ruff check` plus `ruff format --check`. |
| `make types` | `mypy --strict src`. |
| `make test` | Unit, integration, contract and architecture tests. |
| `make e2e` | Playwright end-to-end tests (requires `uv run playwright install chromium`). |
| `make eval-replay` | Replay the committed recorded outputs against the benchmark. |
| `make build` | Build the wheel and sdist. |

The full local gate is:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy --strict src \
  && uv run lint-imports && uv lock --check && uv run pytest -m "not e2e"
```

## Style

- Python 3.12, `src/` layout, fully typed (`mypy --strict`).
- Hexagonal architecture: `domain` is pure, `application` depends on `domain`, and
  `adapters` may depend on both. `tests/architecture` enforces this with import-linter.
- Tests are test-first: write the failing test, implement, then refactor. Never weaken,
  skip or delete a test to make the suite pass.
- No network in tests; the autouse fixture in `tests/conftest.py` blocks non-loopback
  sockets.

## Commits

Use Conventional Commits in English (`feat(guardrails): ...`, `test(eval): ...`,
`docs: ...`, `ci: ...`, `chore: ...`). Keep each commit focused and under roughly 400
changed lines. Do not add AI-attribution trailers.

## Prompt freeze and re-recording

Recorded LLM outputs (cassettes) are keyed by a digest of the exact request. Once real
recordings are committed, any change to prompts, few-shots, the semantic layer,
retrieval parameters, the sanitiser rendering or the warehouse Parquet invalidates
them. The integration test `tests/integration/test_recordings_fresh.py` fails with
`CassetteMiss`; re-record with the Ollama Docker helper and
`sqlagent eval --llm ollama --record`, then commit the new cassettes and baseline in
the same change. This process is finalised with the evaluation tasks.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Please do not open public issues for vulnerabilities.
