"""Composition root: build adapters from typed settings (factory pattern).

Only this module knows which concrete adapter backs each port; the CLI, web UI
and evaluation runner receive ready ports.  ``fake`` backends stay test-only by
constructing ``ScriptedLLM`` directly (D17).
"""

from __future__ import annotations

from pathlib import Path

from sqlagent.adapters.llm.cassette import ReplayLLM
from sqlagent.adapters.llm.ollama import OllamaLLM
from sqlagent.adapters.semantic.fewshots_repository import load_fewshots
from sqlagent.adapters.semantic.yaml_repository import YamlSemanticLayerRepository
from sqlagent.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from sqlagent.adapters.warehouse.etl import BUNDLE_DIR, MANIFEST_NAME
from sqlagent.adapters.warehouse.materialize import ensure_warehouse
from sqlagent.application.agent.events import EventSink
from sqlagent.application.agent.machine import AnalystAgent
from sqlagent.application.ports import LLMPort, WarehouseLimits, WarehousePort
from sqlagent.config import Settings
from sqlagent.domain.errors import ConfigError
from sqlagent.domain.retrieval import Bm25Retriever, FewShot
from sqlagent.domain.semantic import SemanticLayer
from sqlagent.domain.sql_policy import SqlPolicy

DEFAULT_PROMPT_VERSION = "p1"
RESOURCES_DIR = Path(__file__).resolve().parent / "resources"


def model_slug(model: str) -> str:
    """Return the cassette directory name for a model (``:`` becomes ``-``)."""

    return model.replace(":", "-").replace("/", "-")


def default_cassette_path(
    model: str,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> Path:
    """Return the bundled cassette for ``model`` (S22/D18)."""

    return RESOURCES_DIR / "recordings" / model_slug(model) / f"{prompt_version}.jsonl"


def build_llm(
    settings: Settings,
    *,
    cassette_path: Path | None = None,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> LLMPort:
    """Build the configured LLM backend (``ollama`` or ``replay``)."""

    if settings.llm_backend == "ollama":
        return OllamaLLM(settings)
    if settings.llm_backend == "replay":
        return ReplayLLM(cassette_path or default_cassette_path(settings.model, prompt_version))
    raise ConfigError(f"unsupported LLM backend: {settings.llm_backend!r}")  # pragma: no cover


def build_warehouse(
    settings: Settings,
    *,
    bundle_dir: Path = BUNDLE_DIR,
) -> DuckDbWarehouse:
    """Materialise the bundle on first use and return a locked read-only warehouse."""

    path = ensure_warehouse(settings, bundle_dir=bundle_dir)
    limits = WarehouseLimits(
        max_rows=settings.max_rows,
        ui_rows=settings.ui_rows,
        query_timeout_s=settings.query_timeout_s,
        memory_limit=settings.memory_limit,
        threads=settings.threads,
    )
    return DuckDbWarehouse(path, limits, manifest_path=Path(bundle_dir) / MANIFEST_NAME)


def build_semantic() -> SemanticLayer:
    """Load the bundled bilingual semantic layer (S6)."""

    return YamlSemanticLayerRepository().load()


def build_agent(  # noqa: PLR0913 - composition options are explicit
    settings: Settings,
    *,
    llm: LLMPort | None = None,
    warehouse: WarehousePort | None = None,
    semantic: SemanticLayer | None = None,
    sink: EventSink | None = None,
    narrate: bool = True,
    retrieve: bool = True,
    fewshots: tuple[FewShot, ...] | None = None,
) -> AnalystAgent:
    """Compose the analyst state machine from ready or default adapters."""

    resolved_semantic = semantic if semantic is not None else build_semantic()
    resolved_warehouse = warehouse if warehouse is not None else build_warehouse(settings)
    resolved_llm = llm if llm is not None else build_llm(settings)
    resolved_fewshots = load_fewshots() if fewshots is None else fewshots
    retriever = Bm25Retriever(resolved_semantic, resolved_fewshots)
    policy = SqlPolicy(
        catalog_tables=resolved_warehouse.catalog().table_names(),
        max_rows=settings.max_rows,
    )
    return AnalystAgent(
        resolved_llm,
        resolved_warehouse,
        policy,
        retriever,
        resolved_semantic,
        settings,
        sink=sink,
        narrate=narrate,
        retrieve=retrieve,
        fewshots=resolved_fewshots,
    )
