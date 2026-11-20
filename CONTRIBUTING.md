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
| `make smoke` | Build the wheel and run the offline installer smoke test. |
| `make changelog` | Preview the release notes for the latest tag. |
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

Recorded LLM outputs (cassettes) are keyed by a digest of the exact request. Any change
to prompts, few-shots, the semantic layer, retrieval parameters, the sanitiser rendering
or the warehouse Parquet invalidates them. The integration test
`tests/integration/test_recordings_fresh.py` fails with `CassetteMiss`; re-record with
the Ollama Docker helper and `sqlagent eval --llm ollama --record`, then commit the new
cassettes, `eval/baseline.json` and `eval/reports/latest/` in the same change. Do not
update the baseline to hide a regression: the replay gate in CI compares against it.

## CI

GitHub Actions runs on every push to `main` and every pull request:

| Job | What it proves |
|---|---|
| `lint` | `ruff check`, `ruff format --check`, `mypy --strict src`, `lint-imports`, lockfile. |
| `test` | Unit/integration/contract/architecture suite on Ubuntu, Windows and macOS (3.12) plus Ubuntu 3.13; coverage ≥ 85 % on Ubuntu 3.12. |
| `e2e` | Playwright chat journey installed with Chromium on Ubuntu. |
| `eval-gate` | Replays the committed cassettes and fails when EX, refusal accuracy or any category regresses against `eval/baseline.json`. |
| `installer-smoke` | Builds the wheel, installs it with `uv tool install` and runs the console script offline on all three operating systems. |
| `security` | gitleaks over the full history and `pip-audit` on the locked dependencies. |

Run the same jobs locally with `make check`, `make e2e`, `make eval-replay` and
`make smoke`. The smoke test never needs Ollama or a network connection.

## Releases

Releases are driven by annotated tags:

1. Set the same version in `pyproject.toml` and `sqlagent.__version__` (the version is
   read from installed metadata, so no duplicate constant is needed).
2. Update `CHANGELOG.md` and tag `v<version>`.
3. Pushing the tag runs `.github/workflows/release.yml`: it builds the wheel and sdist,
   writes `SHA256SUMS`, runs the installer smoke matrix on Ubuntu, Windows and macOS,
   generates notes from Conventional Commits with git-cliff and publishes the GitHub
   Release with the distributions, checksums, `report.md` and `summary.json`.

Preview the notes locally with `make changelog` (uses `uvx git-cliff`). Never rewrite or
force-push tags that have already been published.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Please do not open public issues for vulnerabilities.
