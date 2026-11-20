"""End-to-end Playwright journey for the web chat (S29/S30/T10).

A real uvicorn server runs in a thread on an ephemeral loopback port with a
scripted LLM and the bundled warehouse, so the browser exercises the actual
HTMX/SSE/Chart.js stack without a model or network egress.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import uvicorn
from PIL import Image
from playwright.sync_api import Page

from sqlagent.adapters.llm.scripted import ScriptedLLM
from sqlagent.adapters.web.app import create_app
from sqlagent.application.ports import LLMRequest
from sqlagent.bootstrap import build_agent, build_semantic, build_warehouse
from sqlagent.config import Settings
from sqlagent.domain.errors import LLMError

pytestmark = pytest.mark.e2e

ANSWER_SQL = (
    "SELECT b.province, COUNT(*) AS n FROM tenders t "
    "JOIN buyers b ON b.buyer_id = t.buyer_id "
    "WHERE b.province IS NOT NULL GROUP BY b.province "
    "ORDER BY n DESC, b.province LIMIT 5"
)


def responder(request: LLMRequest) -> str:
    if request.stage == "narrate":
        return json.dumps({"answer": "Guayas lidera la contratación pública en este almacén."})
    joined = " ".join(str(message.get("content", "")) for message in request.messages)
    if "trigger error" in joined:
        raise LLMError("Ollama is not reachable (e2e)")
    return json.dumps(
        {
            "plan": ["group by province", "order and limit"],
            "action": "final_sql",
            "sql": ANSWER_SQL,
        }
    )


@pytest.fixture(scope="module")
def live_server_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    settings = Settings(
        llm_backend="replay",
        data_dir=tmp_path_factory.mktemp("web-e2e-data"),
        model="scripted",
    )
    warehouse = build_warehouse(settings)
    semantic = build_semantic()
    llm = ScriptedLLM(responder)
    agent = build_agent(settings, llm=llm, warehouse=warehouse, semantic=semantic)
    app = create_app(settings, agent=agent, warehouse=warehouse, semantic=semantic, llm=llm)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:  # pragma: no cover - environment failure
        pytest.fail("uvicorn did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        warehouse.close()


def _non_blank(path: Path) -> bool:
    with Image.open(path) as image:
        low, high = image.convert("L").getextrema()
        return low != high


def _assert_loopback_only(requests: list[str], live_server_url: str) -> None:
    expected = urlsplit(live_server_url).hostname
    external = [
        url
        for url in requests
        if url.startswith(("http://", "https://")) and urlsplit(url).hostname != expected
    ]
    assert external == []


def _focus_textarea_with_tabs(page: Page) -> None:
    for _ in range(20):
        active = page.evaluate("document.activeElement && document.activeElement.id")
        if active == "question":
            return
        page.keyboard.press("Tab")
    pytest.fail("could not reach the question textarea with Tab")


def test_chat_journey_with_sql_table_chart_and_trace(
    page: Page, live_server_url: str, tmp_path: Path
) -> None:
    requests: list[str] = []
    page.on("request", lambda request: requests.append(request.url))
    page.goto(live_server_url, wait_until="networkidle")

    assert page.locator("#question").is_visible()
    assert page.locator(".example").count() == 6
    empty_path = tmp_path / "empty-state.png"
    page.screenshot(path=str(empty_path), full_page=True)
    assert _non_blank(empty_path)

    _focus_textarea_with_tabs(page)
    page.keyboard.type("¿Cuáles son las 5 provincias con más procesos?")
    page.keyboard.press("Enter")

    page.wait_for_selector(".run .answer-card", timeout=30_000)
    page.wait_for_selector("pre.sql-code", timeout=30_000)
    page.wait_for_selector(".result-block .result-table tbody tr", timeout=30_000)
    page.wait_for_selector("canvas", timeout=30_000)
    page.wait_for_selector("details.trace", timeout=30_000)

    assert page.locator(".result-block .result-table tbody tr").count() == 5
    assert "SELECT" in page.locator("pre.sql-code").inner_text()
    assert "Guayas lidera" in page.locator(".narrative").inner_text()
    assert page.locator(".step").count() == 7
    assert page.locator(".step.is-active, .step.is-done").count() >= 1

    # Focus moves to the answer for keyboard and screen-reader users.
    focused = page.evaluate(
        "document.activeElement && document.activeElement.classList.contains('answer-card')"
    )
    assert focused is True

    trace = page.locator("details.trace").first
    trace.locator("summary").click()
    assert trace.locator("[data-field='llm_calls']").is_visible()

    page.locator("#theme-toggle").click()
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"

    _assert_loopback_only(requests, live_server_url)


def test_language_toggle_and_mobile_layout(page: Page, live_server_url: str) -> None:
    page.set_viewport_size({"width": 360, "height": 740})
    page.goto(live_server_url, wait_until="networkidle")

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    with page.expect_navigation():
        page.locator("#lang-toggle").click()
    assert page.evaluate("document.documentElement.lang") == "en"
    assert "Your question" in page.locator("label[for='question']").inner_text()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_error_state_is_rendered_and_not_blank(
    page: Page, live_server_url: str, tmp_path: Path
) -> None:
    page.goto(live_server_url, wait_until="networkidle")
    page.fill("#question", "trigger error please")
    page.locator("#composer button[type='submit']").click()

    page.wait_for_selector(".notice--error", timeout=30_000)
    assert "sqlagent doctor" in page.locator(".notice--error").inner_text().lower()
    assert page.locator(".run[aria-busy='false']").count() >= 1
    error_path = tmp_path / "error-state.png"
    page.screenshot(path=str(error_path), full_page=True)
    assert _non_blank(error_path)


def test_static_vendor_assets_are_served_from_loopback(page: Page, live_server_url: str) -> None:
    for asset in (
        "/static/vendor/htmx.min.js",
        "/static/vendor/sse.min.js",
        "/static/vendor/chart.umd.min.js",
        "/static/chat.js",
    ):
        response = page.request.get(live_server_url + asset)
        assert response.ok, asset
        assert "javascript" in response.headers.get("content-type", "").lower() or asset.endswith(
            ".js"
        )
