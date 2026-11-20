.PHONY: install lint types test e2e eval-replay smoke changelog build check

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

types:
	uv run mypy --strict src

test:
	uv run pytest -m "not e2e"

e2e:
	uv run pytest -m e2e

eval-replay:
	uv run sqlagent eval --llm replay

smoke: build
	uv run python scripts/smoke_install.py

changelog:
	uvx git-cliff --latest --strip header

build:
	uv build

check: lint types test
