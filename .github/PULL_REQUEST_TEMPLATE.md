## Summary

Describe the change and the problem it solves.

## Type of change

- [ ] Feature
- [ ] Fix
- [ ] Documentation
- [ ] Refactor / performance
- [ ] CI / tooling

## Test plan

- [ ] `uv run ruff check . && uv run ruff format --check .`
- [ ] `uv run mypy --strict src`
- [ ] `uv run lint-imports`
- [ ] `uv run pytest -m "not e2e"`

## Checklist

- [ ] Tests were written first and cover the new behaviour (no weakened/skipped tests).
- [ ] No secrets, personal data or absolute local paths are committed.
- [ ] Documentation and changelog updated when behaviour changed.
- [ ] No AI-attribution trailers in commits.
