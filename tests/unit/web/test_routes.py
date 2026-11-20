"""Web routes: HTML, JSON, SSE ordering, security headers and XSS escaping (D24)."""

from __future__ import annotations

import json
import re

import httpx
import pytest
from starlette.testclient import TestClient

from sqlagent.adapters.web.app import create_app
from sqlagent.domain.errors import ConfigError
from sqlagent.domain.models import Language

from .conftest import failing_responder, scripted_responder, write_poisoned_sql

pytestmark = pytest.mark.unit

STREAM_ID = re.compile(r"/ask/stream/([0-9a-f]+)")


def events(response: httpx.Response) -> list[str]:
    names: list[str] = []
    for line in response.iter_lines():
        if line.startswith("event:"):
            names.append(line.split(":", 1)[1].strip())
    return names


def stream_for(client: TestClient, question: str, language: str = "es") -> httpx.Response:
    created = client.post("/ask", data={"question": question, "lang": language})
    assert created.status_code == 200
    match = STREAM_ID.search(created.text)
    assert match is not None, created.text
    return client.get(f"/ask/stream/{match.group(1)}")


def test_index_renders_chat_shell(make_app) -> None:
    client = TestClient(make_app())
    response = client.get("/")

    assert response.status_code == 200
    assert 'lang="es"' in response.text
    assert 'hx-post="/ask"' in response.text
    assert 'name="question"' in response.text
    assert response.text.count('class="example"') == 6
    assert 'id="theme-toggle"' in response.text


def test_health_returns_backend_and_warehouse(make_app) -> None:
    client = TestClient(make_app())
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "scripted"
    assert body["model"] == "scripted"
    assert body["warehouse"]["tables"]["tenders"] == 121_072
    assert body["version"]


def test_schema_drawer_lists_tables_columns_and_attribution(make_app) -> None:
    client = TestClient(make_app())
    response = client.get("/schema")

    assert response.status_code == 200
    assert "tenders" in response.text
    assert "buyer_id" in response.text
    assert "CC BY 3.0" in response.text
    assert "SERCOP" in response.text


@pytest.mark.parametrize("path", ["/", "/health", "/schema"])
def test_security_headers_on_every_response(make_app, path: str) -> None:
    client = TestClient(make_app())
    response = client.get(path)

    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/ask", {"question": "¿Cuántos procesos hay?", "lang": "es"}),
        ("/api/ask", {"question": "How many tenders are there?", "lang": "en"}),
    ],
)
def test_foreign_origin_is_rejected(make_app, path: str, payload: dict[str, str]) -> None:
    client = TestClient(make_app())
    response = client.post(
        path,
        data=payload if path == "/ask" else None,
        json=payload if path == "/api/ask" else None,
        headers={"Origin": "http://evil.example"},
    )

    assert response.status_code == 403


def test_api_ask_returns_json_answer(make_app) -> None:
    client = TestClient(make_app())
    response = client.post(
        "/api/ask",
        json={"question": "¿Cuáles son las 5 provincias con más procesos?", "lang": "es"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["language"] == "es"
    assert body["sql"].startswith("SELECT b.province")
    assert len(body["result"]["rows"]) == 5
    assert body["chart"]["kind"] in {"bar", "hbar"}
    assert body["trace"]["llm_calls"] == 2
    assert body["answer_id"]


def test_sse_event_order(make_app) -> None:
    client = TestClient(make_app())
    stream = stream_for(client, "¿Cuáles son las 5 provincias con más procesos?")

    assert stream.status_code == 200
    names = events(stream)
    assert names[0] == "phase"
    for required in ("sql", "result", "chart", "answer", "done"):
        assert required in names
    assert names.index("sql") < names.index("result") < names.index("chart")
    assert names.index("chart") < names.index("answer") < names.index("done")
    assert names[-1] == "done"


def test_sse_answer_includes_trace_and_narrative(make_app) -> None:
    client = TestClient(make_app())
    stream = stream_for(client, "¿Cuáles son las 5 provincias con más procesos?")
    payload = stream.text

    assert "Guayas lidera" in payload
    assert "trace" in payload
    assert "llm_calls" in payload


def test_sse_error_event_on_llm_failure(make_app) -> None:
    client = TestClient(make_app(failing_responder()))
    stream = stream_for(client, "How many tenders are there?", language="en")

    names = events(stream)
    assert "error" in names
    assert "answer" in names
    assert names[-1] == "done"


def test_stream_unknown_id_is_404(make_app) -> None:
    client = TestClient(make_app())
    assert client.get("/ask/stream/doesnotexist").status_code == 404


def test_xss_payload_is_escaped_in_html(make_app) -> None:
    client = TestClient(make_app(scripted_responder(sql=write_poisoned_sql())))
    stream = stream_for(client, "show the payload")

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in stream.text
    assert "<script>alert(1)</script>" not in stream.text


def test_xss_payload_is_escaped_in_json_fragment_page(make_app) -> None:
    client = TestClient(make_app(scripted_responder(sql=write_poisoned_sql())))
    response = client.post(
        "/api/ask",
        data={"question": "show the payload", "lang": "en"},
        headers={"Accept": "text/html"},
    )

    assert response.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text


def test_csv_export_round_trip(make_app) -> None:
    client = TestClient(make_app())
    answer = client.post(
        "/api/ask", json={"question": "¿Cuáles son las 5 provincias?", "lang": "es"}
    ).json()

    response = client.get(f"/export/{answer['answer_id']}.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert lines[0].split(",") == ["province", "n"]
    assert len(lines) == 6


def test_csv_export_unknown_id_is_404(make_app) -> None:
    client = TestClient(make_app())
    assert client.get("/export/missing.csv").status_code == 404


def test_language_query_and_hidden_field(make_app) -> None:
    client = TestClient(make_app())
    html = client.get("/?lang=en").text

    assert 'lang="en"' in html
    assert 'value="en"' in html
    assert 'name="lang"' in html


def test_sample_values_from_real_warehouse(make_app) -> None:
    """The default SQL runs against the bundled warehouse, not a stub."""

    client = TestClient(make_app())
    answer = client.post("/api/ask", json={"question": "provincias", "lang": "es"}).json()

    assert answer["result"]["row_count"] == 5
    assert all(isinstance(row[1], int) for row in answer["result"]["rows"])
    assert answer["chart"]["kind"] in {"bar", "hbar"}


def test_ask_route_detects_language_when_auto(make_app) -> None:
    client = TestClient(make_app())
    body = client.post(
        "/api/ask", json={"question": "How many tenders are there?", "lang": "auto"}
    ).json()

    assert body["language"] == Language.EN


def test_create_app_rejects_custom_agent_without_dependencies(web_settings) -> None:
    with pytest.raises(ConfigError):
        create_app(web_settings, agent=object())  # type: ignore[arg-type]


def test_json_ask_uses_same_agent_and_returns_json_serialisable(make_app) -> None:
    client = TestClient(make_app())
    response = client.post("/api/ask", json={"question": "question", "lang": "es"})

    assert response.headers["content-type"].startswith("application/json")
    json.dumps(response.json())  # exactly one JSON document
