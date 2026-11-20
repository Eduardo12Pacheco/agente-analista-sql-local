"""YAML benchmark repository (S23): loads ``resources/benchmark/<version>``."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from sqlagent.application.evaluation.benchmark import BENCHMARK_VERSION, Benchmark
from sqlagent.domain.errors import ConfigError

DEFAULT_BENCHMARK_DIR = Path(__file__).resolve().parents[2] / "resources" / "benchmark"
QUESTIONS_FILENAME = "questions.yaml"


class YamlBenchmarkRepository:
    """Load the versioned benchmark list, validating every item eagerly."""

    def __init__(self, benchmark_dir: Path | None = None) -> None:
        self._benchmark_dir = (
            Path(benchmark_dir) if benchmark_dir is not None else DEFAULT_BENCHMARK_DIR
        )

    @property
    def benchmark_dir(self) -> Path:
        return self._benchmark_dir

    def questions_path(self, version: str = BENCHMARK_VERSION) -> Path:
        return self._benchmark_dir / version / QUESTIONS_FILENAME

    def load(self, version: str = BENCHMARK_VERSION) -> Benchmark:
        """Read and validate one benchmark version from disk."""

        path = self.questions_path(version)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"cannot read benchmark {path.name} for {version}: {exc}") from exc
        except yaml.YAMLError as exc:
            raise ConfigError(f"cannot parse benchmark {path.name}: {exc}") from exc
        if not isinstance(raw, list):
            raise ConfigError(f"benchmark {path.name} must contain a list of items")
        try:
            return Benchmark.model_validate({"version": version, "items": raw})
        except ValidationError as exc:
            raise ConfigError(f"invalid benchmark {path.name}: {exc}") from exc


def load_benchmark(version: str = BENCHMARK_VERSION) -> Benchmark:
    """Convenience loader for the bundled benchmark."""

    return YamlBenchmarkRepository().load(version)


__all__ = [
    "DEFAULT_BENCHMARK_DIR",
    "QUESTIONS_FILENAME",
    "YamlBenchmarkRepository",
    "load_benchmark",
]
