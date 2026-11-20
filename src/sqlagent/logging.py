"""Structured logging (D27) with request-scoped context.

Console rendering is used for TTYs and tests; ``LOG_FORMAT=json`` emits one JSON
object per line for machines.  Logs go to stderr so ``sqlagent --json`` keeps
stdout as exactly one document (D25).
"""

from __future__ import annotations

import io
import logging
import sys
from typing import TextIO, cast

import structlog

from sqlagent.config import Settings


class _CurrentStderr(io.TextIOBase):
    """A file-like proxy resolving ``sys.stderr`` at write time.

    ``PrintLoggerFactory`` stores the stream it is given; capturing the actual
    ``sys.stderr`` object would keep writing to a closed stream after a test
    runner or a CLI harness swaps it.  Resolving per call keeps logs flowing to
    whatever stderr is current.
    """

    def write(self, message: str) -> int:
        return sys.stderr.write(message)

    def flush(self) -> None:
        sys.stderr.flush()


def configure_logging(settings: Settings | None = None) -> None:
    """Install the structlog pipeline; safe to call more than once."""

    settings = settings or Settings()
    level = getattr(logging, settings.log_level)
    if settings.log_format == "json":
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=cast(TextIO, _CurrentStderr())),
        cache_logger_on_first_use=True,
    )


def bind_request_context(*, request_id: str, question_id: str | None = None) -> None:
    """Attach the per-request identifiers used by every subsequent log event."""

    context: dict[str, str | None] = {"request_id": request_id}
    if question_id is not None:
        context["question_id"] = question_id
    structlog.contextvars.bind_contextvars(**context)


def clear_request_context() -> None:
    """Remove all request-scoped log context."""

    structlog.contextvars.clear_contextvars()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger for ``name`` (module-level callers use ``__name__``)."""

    return structlog.get_logger(name)  # type: ignore[no-any-return]
