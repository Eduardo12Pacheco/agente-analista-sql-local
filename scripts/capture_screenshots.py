"""Capture the README screenshots and demo GIF from the real web chat (T14/D32).

The script starts the actual FastAPI application with the replay backend (the
committed cassette, no model and no network), drives Chromium through the real
HTMX/SSE/Chart.js flow and writes the assets used by both READMEs.

Usage::

    uv run python scripts/capture_screenshots.py
    uv run python scripts/capture_screenshots.py --out docs/assets
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from PIL import Image
from playwright.sync_api import Locator, Page, sync_playwright

from sqlagent.adapters.web.app import create_app
from sqlagent.config import Settings

VIEWPORT = {"width": 1280, "height": 800}
GIF_WIDTH = 800
GIF_FRAME_MS = 1600

# Benchmark v1 items that the committed cassette answers. q042 is Spanish with a
# bar chart, q050 is English with a line chart and q063 exercises entity
# resolution against a public buyer name.
ANSWER_BAR_ES = "¿Cuáles son los 5 cantones con más procesos de contratación?"
ANSWER_LINE_EN = "How many competitive tenders were published per month?"
ANSWER_ENTITY_ES = "¿Cuántos procesos publicó la Contraloría?"


def _start_server() -> tuple[uvicorn.Server, threading.Thread, str]:
    data_dir = Path(tempfile.mkdtemp(prefix="sqlagent-screenshots-"))
    settings = Settings(llm_backend="replay", data_dir=data_dir)
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("uvicorn did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, f"http://127.0.0.1:{port}"


def _stop_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    state = getattr(server.config.app.state, "web", None)
    server.should_exit = True
    thread.join(timeout=10)
    if state is not None:
        state.warehouse.close()


def _shot(page: Page, path: Path) -> None:
    page.screenshot(path=str(path), animations="disabled")


def _run_for(page: Page, question: str) -> Locator:
    return page.locator(".run", has_text=question).first


def _ask(page: Page, question: str) -> None:
    page.fill("#question", question)
    page.press("#question", "Enter")
    # Runs are prepended to the conversation, so identify the answer by its
    # question text instead of by DOM position.
    page.locator(".run[aria-busy='false']", has_text=question).first.wait_for(
        state="visible", timeout=90_000
    )
    run = _run_for(page, question)
    run.wait_for(state="visible")
    # Chart.js draws asynchronously; wait for the canvas (or the KPI text) and settle.
    try:
        run.locator("canvas").first.wait_for(state="visible", timeout=10_000)
    except Exception:  # KPI answers have no canvas
        run.locator(".kpi-value").first.wait_for(state="visible", timeout=10_000)
    page.wait_for_timeout(900)


ANSWER_MARGIN_PX = 32
# Smaller top margin keeps the bottom edge of the composer out of the frame.
ANSWER_TOP_MARGIN_PX = 12


def _shot_answer(page: Page, question: str, path: Path) -> None:
    """Capture the whole answer run with a margin, so the card is never cut off.

    The run is taller than the 800 px viewport, so a viewport shot would crop
    its header or its bottom edge. The focus ring the app puts on the new answer
    is cleared first so it does not frame the card in the README image.
    """

    box = _run_for(page, question).bounding_box()
    if box is None:
        raise RuntimeError("answer run is not visible")
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    scroll_y = page.evaluate("() => window.scrollY")
    side = ANSWER_MARGIN_PX
    page.screenshot(
        path=str(path),
        animations="disabled",
        full_page=True,
        clip={
            "x": box["x"] - side,
            "y": box["y"] + scroll_y - ANSWER_TOP_MARGIN_PX,
            "width": box["width"] + 2 * side,
            "height": box["height"] + ANSWER_TOP_MARGIN_PX + side,
        },
    )


def _frame_frames(page: Page, tmp: Path, names: list[Path]) -> None:
    path = tmp / f"frame-{len(names) + 1:02d}.png"
    _shot(page, path)
    names.append(path)


def _write_gif(frames: list[Path], out: Path) -> None:
    images: list[Image.Image] = []
    for path in frames:
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((GIF_WIDTH, GIF_WIDTH * 2), Image.Resampling.LANCZOS)
            images.append(image.convert("P", palette=Image.Palette.ADAPTIVE, colors=128))
    if not images:
        raise RuntimeError("no frames captured")
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=GIF_FRAME_MS,
        loop=0,
        optimize=True,
    )


def _capture_assets(page: Page, url: str, out_dir: Path, tmp: Path, frames: list[Path]) -> None:
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector("#question")
    _shot(page, out_dir / "empty-state.png")
    _frame_frames(page, tmp, frames)

    _ask(page, ANSWER_BAR_ES)
    _shot_answer(page, ANSWER_BAR_ES, out_dir / "hero-light.png")
    _frame_frames(page, tmp, frames)

    page.locator("#theme-toggle").click()
    page.wait_for_timeout(400)
    _shot_answer(page, ANSWER_BAR_ES, out_dir / "hero-dark.png")
    _frame_frames(page, tmp, frames)

    page.locator("#theme-toggle").click()
    page.wait_for_timeout(300)
    # The composer forwards the UI language to the agent, and the cassette was
    # recorded with auto-detected question languages, so switch the UI before
    # asking the English question.
    page.locator("#lang-toggle").click()
    page.wait_for_load_state("networkidle")
    _ask(page, ANSWER_LINE_EN)
    _shot_answer(page, ANSWER_LINE_EN, out_dir / "answer-chart.png")
    _frame_frames(page, tmp, frames)

    page.locator("#lang-toggle").click()
    page.wait_for_load_state("networkidle")
    _ask(page, ANSWER_ENTITY_ES)
    _run_for(page, ANSWER_ENTITY_ES).scroll_into_view_if_needed()
    _frame_frames(page, tmp, frames)

    page.locator(".data-drawer summary").click()
    page.wait_for_selector(".data-drawer .schema-table", state="visible")
    page.locator(".data-drawer .schema-table summary").first.click()
    page.wait_for_timeout(300)
    page.locator(".data-drawer").scroll_into_view_if_needed()
    _frame_frames(page, tmp, frames)


def capture(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    server, thread, url = _start_server()
    frames: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix="sqlagent-frames-") as raw_tmp:
            tmp = Path(raw_tmp)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport=VIEWPORT, color_scheme="light")
                page = context.new_page()
                _capture_assets(page, url, out_dir, tmp, frames)
                context.close()
                browser.close()
            _write_gif(frames, out_dir / "demo.gif")
    finally:
        _stop_server(server, thread)
    return [
        out_dir / "hero-light.png",
        out_dir / "hero-dark.png",
        out_dir / "answer-chart.png",
        out_dir / "empty-state.png",
        out_dir / "demo.gif",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/assets"))
    args = parser.parse_args(argv)
    try:
        paths = capture(args.out)
    except Exception as exc:
        print(f"error: screenshot capture failed: {exc}", file=sys.stderr)
        return 1
    for path in paths:
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
