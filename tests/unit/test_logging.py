"""Tests for structured logging configuration (D27)."""

from __future__ import annotations

import json

import structlog

from sqlagent.config import Settings
from sqlagent.logging import (
    bind_request_context,
    clear_request_context,
    configure_logging,
    get_logger,
)


def test_json_log_event_contains_level_context_and_fields(capsys) -> None:  # type: ignore[no-untyped-def]
    configure_logging(Settings(log_format="json", log_level="INFO"))
    bind_request_context(request_id="req-1", question_id="q001")
    try:
        get_logger("test").info("llm.call", stage="generate", tokens=10)
    finally:
        clear_request_context()

    captured = capsys.readouterr()
    payload = json.loads(captured.err.strip().splitlines()[-1])
    assert payload["event"] == "llm.call"
    assert payload["level"] == "info"
    assert payload["stage"] == "generate"
    assert payload["tokens"] == 10
    assert payload["request_id"] == "req-1"
    assert payload["question_id"] == "q001"
    assert "timestamp" in payload


def test_level_filtering_and_console_renderer(capsys) -> None:  # type: ignore[no-untyped-def]
    configure_logging(Settings(log_format="console", log_level="WARNING"))
    logger = get_logger("test")
    logger.info("hidden")
    logger.warning("visible", detail="x")

    captured = capsys.readouterr()
    assert "hidden" not in captured.err
    assert "visible" in captured.err


def test_clear_context_removes_request_ids(capsys) -> None:  # type: ignore[no-untyped-def]
    configure_logging(Settings(log_format="json", log_level="INFO"))
    bind_request_context(request_id="req-2")
    clear_request_context()
    get_logger("test").info("agent.done", status="ok")

    payload = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert "request_id" not in payload
    assert payload["status"] == "ok"


def test_structlog_configured_processor_chain_is_json() -> None:
    configure_logging(Settings(log_format="json"))

    assert structlog.is_configured()
