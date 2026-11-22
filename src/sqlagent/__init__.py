"""Local-first AI data analyst over a bundled DuckDB warehouse."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("local-sql-analyst-agent")
except PackageNotFoundError:  # pragma: no cover - only when running from a raw checkout
    __version__ = "0.1.0"

REPOSITORY_URL = "https://github.com/Eduardo12Pacheco/agente-analista-sql-local"

__all__ = ["REPOSITORY_URL", "__version__"]
