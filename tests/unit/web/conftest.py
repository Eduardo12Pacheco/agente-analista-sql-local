"""Shared web test fixtures: a real bundled warehouse and scripted agents."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from sqlagent.adapters.llm.scripted import ScriptedLLM
from sqlagent.adapters.web.app import create_app
from sqlagent.application.ports import LLMRequest
from sqlagent.application.use_cases.ask import AskQuestion
from sqlagent.bootstrap import build_agent, build_semantic, build_warehouse
from sqlagent.config import Settings
from sqlagent.domain.errors import LLMError

DEFAULT_SQL = (
    "SELECT b.province, COUNT(*) AS n FROM tenders t "
    "JOIN buyers b ON b.buyer_id = t.buyer_id "
    "WHERE b.province IS NOT NULL GROUP BY b.province ORDER BY n DESC, b.province LIMIT 5"
)

Responder = Callable[[LLMRequest], str]


def final_sql(sql: str = DEFAULT_SQL) -> str:
    return json.dumps({"plan": ["count by province"], "action": "final_sql", "sql": sql})


def narration(text: str = "Guayas lidera el número de procesos.") -> str:
    return json.dumps({"answer": text})


def scripted_responder(
    *,
    sql: str = DEFAULT_SQL,
    text: str = "Guayas lidera el número de procesos.",
) -> Responder:
    def responder(request: LLMRequest) -> str:
        if request.stage == "narrate":
            return narration(text)
        return final_sql(sql)

    return responder


def failing_responder(message: str = "Ollama is not reachable") -> Responder:
    def responder(request: LLMRequest) -> str:
        raise LLMError(message)

    return responder


@pytest.fixture(scope="session")
def web_settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    data_dir = tmp_path_factory.mktemp("web-data")
    return Settings(llm_backend="replay", data_dir=data_dir, model="scripted")


@pytest.fixture(scope="session")
def web_warehouse(web_settings: Settings):
    warehouse = build_warehouse(web_settings)
    yield warehouse
    warehouse.close()


@pytest.fixture(scope="session")
def web_semantic():
    return build_semantic()


@pytest.fixture
def make_app(web_settings: Settings, web_warehouse, web_semantic):
    def factory(responder: Responder | None = None):
        llm = ScriptedLLM(responder or scripted_responder())
        agent = build_agent(
            web_settings,
            llm=llm,
            warehouse=web_warehouse,
            semantic=web_semantic,
            narrate=True,
        )
        return create_app(
            web_settings,
            agent=agent,
            warehouse=web_warehouse,
            semantic=web_semantic,
            llm=llm,
        )

    return factory


@pytest.fixture
def ask(web_settings: Settings, web_warehouse, web_semantic):
    def factory(responder: Responder | None = None) -> AskQuestion:
        llm = ScriptedLLM(responder or scripted_responder())
        agent = build_agent(
            web_settings,
            llm=llm,
            warehouse=web_warehouse,
            semantic=web_semantic,
            narrate=True,
        )
        return AskQuestion(agent)

    return factory


def write_poisoned_sql() -> str:
    """A read-only SELECT whose value is an HTML/script injection payload."""

    return "SELECT '<script>alert(1)</script>' AS label, 1 AS n"
