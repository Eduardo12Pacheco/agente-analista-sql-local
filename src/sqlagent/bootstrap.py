"""Composition root: build adapters from typed settings (factory pattern).

Only this module knows which concrete adapter backs each port; the CLI, web UI
and evaluation runner receive ready ports.  ``fake`` backends stay test-only by
constructing ``ScriptedLLM`` directly (D17).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlagent.adapters.llm.cassette import ReplayLLM
from sqlagent.adapters.llm.ollama import OllamaLLM
from sqlagent.adapters.semantic.fewshots_repository import load_fewshots
from sqlagent.adapters.semantic.manifest_repository import ManifestSemanticLayerRepository
from sqlagent.adapters.semantic.yaml_repository import YamlSemanticLayerRepository
from sqlagent.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from sqlagent.adapters.warehouse.etl import BUNDLE_DIR, MANIFEST_NAME
from sqlagent.adapters.warehouse.lakehouse import LakehouseManifest, open_lakehouse
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
    return DuckDbWarehouse(
        path,
        warehouse_limits(settings),
        manifest_path=Path(bundle_dir) / MANIFEST_NAME,
    )


def warehouse_limits(settings: Settings) -> WarehouseLimits:
    """Map settings onto the warehouse limits shared by both adapters (D15)."""

    return WarehouseLimits(
        max_rows=settings.max_rows,
        ui_rows=settings.ui_rows,
        query_timeout_s=settings.query_timeout_s,
        memory_limit=settings.memory_limit,
        threads=settings.threads,
    )


@dataclass(frozen=True, slots=True)
class Runtime:
    """Ports and resources selected for one settings snapshot (T11)."""

    warehouse: WarehousePort
    semantic: SemanticLayer
    fewshots: tuple[FewShot, ...]
    lakehouse: LakehouseManifest | None = None

    @property
    def external(self) -> bool:
        return self.lakehouse is not None


def build_runtime(settings: Settings) -> Runtime:
    """Build the runtime for the bundled warehouse or an external lakehouse (S31).

    An external manifest replaces the Parquet bundle, the bundled semantic layer
    and the few-shot examples; metrics and glossary stay empty because the
    manifest contract does not carry them (D28).
    """

    if settings.lakehouse_manifest is not None:
        manifest_path = Path(settings.lakehouse_manifest)
        warehouse = open_lakehouse(manifest_path, warehouse_limits(settings))
        semantic = ManifestSemanticLayerRepository(warehouse.manifest).load()
        return Runtime(
            warehouse=warehouse,
            semantic=semantic,
            fewshots=(),
            lakehouse=warehouse.manifest,
        )
    return Runtime(
        warehouse=build_warehouse(settings),
        semantic=build_semantic(),
        fewshots=load_fewshots(),
    )


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

    runtime: Runtime | None = None
    resolved_warehouse = warehouse
    resolved_semantic = semantic
    if settings.lakehouse_manifest is not None and (
        resolved_warehouse is None or resolved_semantic is None
    ):
        runtime = build_runtime(settings)
        if resolved_warehouse is None:
            resolved_warehouse = runtime.warehouse
        if resolved_semantic is None:
            resolved_semantic = runtime.semantic
    if resolved_warehouse is None:
        resolved_warehouse = build_warehouse(settings)
    if resolved_semantic is None:
        resolved_semantic = build_semantic()
    resolved_llm = llm if llm is not None else build_llm(settings)
    if fewshots is not None:
        resolved_fewshots = fewshots
    elif runtime is not None:
        resolved_fewshots = runtime.fewshots
    else:
        resolved_fewshots = load_fewshots()
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
