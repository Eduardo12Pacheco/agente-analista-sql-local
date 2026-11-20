#!/usr/bin/env python
"""Write (or check) benchmark v1's lock file (S23/D18).

Run after editing ``questions.yaml`` or rebuilding the warehouse manifest:

    uv run python scripts/lock_benchmark.py

Exit codes: 0 lock written or matches; 2 the committed lock is stale (``--check``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlagent.adapters.benchmark.yaml_repository import (
    DEFAULT_BENCHMARK_DIR,
    YamlBenchmarkRepository,
)
from sqlagent.adapters.warehouse.etl import BUNDLE_DIR, MANIFEST_NAME
from sqlagent.application.evaluation.benchmark import BENCHMARK_VERSION, build_lock

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "src/sqlagent/resources/benchmark"
QUESTIONS_PATH = BENCHMARK_DIR / BENCHMARK_VERSION / "questions.yaml"
LOCK_PATH = BENCHMARK_DIR / BENCHMARK_VERSION / "benchmark.lock.json"
MANIFEST_PATH = REPO_ROOT / "src/sqlagent/resources/warehouse" / MANIFEST_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lock or check the benchmark v1 hashes and counts")
    parser.add_argument(
        "--check", action="store_true", help="exit 2 when the committed lock is stale"
    )
    parser.add_argument(
        "--version", default=BENCHMARK_VERSION, help="benchmark version (default: v1)"
    )
    args = parser.parse_args(argv)

    repository = YamlBenchmarkRepository(DEFAULT_BENCHMARK_DIR)
    benchmark = repository.load(args.version)
    questions_path = repository.questions_path(args.version)
    manifest_path = MANIFEST_PATH if MANIFEST_PATH.exists() else Path(BUNDLE_DIR) / MANIFEST_NAME
    lock = build_lock(benchmark, questions_path, manifest_path)
    payload = json.dumps(lock.model_dump(), indent=2, ensure_ascii=False) + "\n"
    lock_path = questions_path.parent / "benchmark.lock.json"

    if args.check:
        if not lock_path.exists():
            print(f"stale: {lock_path} is missing", file=sys.stderr)
            return 2
        if lock_path.read_text(encoding="utf-8") != payload:
            print(f"stale: {lock_path} does not match questions.yaml/manifest", file=sys.stderr)
            return 2
        print(f"lock OK: {lock_path} ({lock.n} items)")
        return 0

    lock_path.write_text(payload, encoding="utf-8")
    print(f"wrote {lock_path} ({lock.n} items, {len(benchmark.pairs())} pairs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
