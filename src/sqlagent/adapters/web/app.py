"""FastAPI application factory for the local chat (S29/S30/D23/D24).

The factory is the composition point for the web adapter: it receives ready
ports (or builds the defaults through the existing composition root), attaches
the shared Jinja environment and mounts the routes.  Security headers and the
same-origin POST check live here so no route can forget them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from sqlagent import __version__
from sqlagent.adapters.web.i18n import DEFAULT_LANGUAGE, normalize_language
from sqlagent.adapters.web.routes import router
from sqlagent.adapters.web.sse import RunStore
from sqlagent.adapters.web.templating import TEMPLATES_DIR, templates
from sqlagent.application.agent.machine import AnalystAgent
from sqlagent.application.ports import LLMPort, WarehousePort
from sqlagent.application.use_cases.ask import AskQuestion
from sqlagent.bootstrap import build_agent, build_llm, build_semantic, build_warehouse
from sqlagent.config import Settings
from sqlagent.domain.errors import ConfigError
from sqlagent.domain.semantic import SemanticLayer

logger = structlog.get_logger(__name__)

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
SAME_ORIGIN_POST_PATHS = frozenset({"/ask", "/api/ask"})


@dataclass
class WebState:
    """Everything the route layer needs, built once per app."""

    settings: Settings
    agent: AnalystAgent
    warehouse: WarehousePort
    semantic: SemanticLayer
    llm: LLMPort
    store: RunStore = field(default_factory=RunStore)
    ask: AskQuestion | None = None

    def __post_init__(self) -> None:
        if self.ask is None:
            self.ask = AskQuestion(self.agent)

    @property
    def demo(self) -> bool:
        return self.settings.llm_backend == "replay"

    @property
    def backend(self) -> str:
        return self.llm.describe().backend

    @property
    def model(self) -> str:
        return self.llm.describe().model or self.settings.model

    @property
    def version(self) -> str:
        return __version__


def _language_for(request: Request, state: WebState) -> str:
    requested = request.query_params.get("lang")
    if requested:
        return normalize_language(requested)
    if state.settings.ui_lang != "auto":
        return normalize_language(state.settings.ui_lang)
    header = request.headers.get("accept-language")
    if header:
        for candidate in header.split(","):
            code = candidate.split(";", 1)[0].strip()
            if code.lower().startswith(("es", "en")):
                return normalize_language(code)
    return DEFAULT_LANGUAGE


def ollama_ok(state: WebState) -> bool:
    if state.settings.llm_backend != "ollama":
        return True
    probe = getattr(state.llm, "probe", None)
    if not callable(probe):
        return True
    try:
        return bool(probe().reachable)
    except Exception:  # health must never raise
        return False


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("host", "")
    try:
        return urlsplit(origin).netloc == host
    except ValueError:
        return False


def _attach_security_headers(response: Response) -> Response:
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


def create_app(
    settings: Settings | None = None,
    *,
    agent: AnalystAgent | None = None,
    warehouse: WarehousePort | None = None,
    semantic: SemanticLayer | None = None,
    llm: LLMPort | None = None,
) -> FastAPI:
    """Build the web application around ready ports or the bundled defaults."""

    resolved_settings = settings or Settings()
    if agent is not None:
        if warehouse is None or semantic is None:
            raise ConfigError(
                "create_app() needs warehouse and semantic when a custom agent is injected"
            )
        resolved_warehouse = warehouse
        resolved_semantic = semantic
        resolved_llm = llm or build_llm(resolved_settings)
        resolved_agent = agent
    else:
        resolved_warehouse = warehouse or build_warehouse(resolved_settings)
        resolved_semantic = semantic or build_semantic()
        resolved_llm = llm or build_llm(resolved_settings)
        resolved_agent = build_agent(
            resolved_settings,
            llm=resolved_llm,
            warehouse=resolved_warehouse,
            semantic=resolved_semantic,
        )

    state = WebState(
        settings=resolved_settings,
        agent=resolved_agent,
        warehouse=resolved_warehouse,
        semantic=resolved_semantic,
        llm=resolved_llm,
    )
    app = FastAPI(
        title="sqlagent web",
        version=state.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.web = state
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        if (
            request.method == "POST"
            and request.url.path in SAME_ORIGIN_POST_PATHS
            and not _origin_allowed(request)
        ):
            return _attach_security_headers(
                JSONResponse({"error": "cross-origin POST rejected"}, status_code=403)
            )
        response = await call_next(request)
        return _attach_security_headers(response)

    return app


def language_for_request(request: Request) -> str:
    """Public helper used by the routes module."""

    return _language_for(request, request.app.state.web)


__all__ = [
    "CONTENT_SECURITY_POLICY",
    "STATIC_DIR",
    "TEMPLATES_DIR",
    "WebState",
    "create_app",
    "language_for_request",
    "ollama_ok",
    "templates",
]
