"""Typed domain errors shared across the hexagon.

``GuardrailCode`` lives here (T2 decision) so every layer can inspect a
rejection without importing the SQL-policy adapter-facing module; T3 will
re-export it from ``sql_policy``.
"""

from __future__ import annotations

from enum import StrEnum


class GuardrailCode(StrEnum):
    """Stable, machine-readable SQL guardrail rejection reasons (D14).

    The member names and values are the exact D14 contract: downstream layers
    (agent refusal handling, evaluation taxonomy, UI badges) key off them.
    """

    EMPTY = "EMPTY"
    TOO_LONG = "TOO_LONG"
    PARSE_ERROR = "PARSE_ERROR"
    MULTI_STATEMENT = "MULTI_STATEMENT"
    NOT_SELECT = "NOT_SELECT"
    FORBIDDEN_NODE = "FORBIDDEN_NODE"
    FORBIDDEN_FUNCTION = "FORBIDDEN_FUNCTION"
    UNKNOWN_TABLE = "UNKNOWN_TABLE"
    TABLE_FUNCTION = "TABLE_FUNCTION"
    TOO_COMPLEX = "TOO_COMPLEX"


class SqlAgentError(Exception):
    """Base class for every expected (non-programming) failure."""


class GuardrailViolation(SqlAgentError):
    """A SQL statement was rejected before touching the warehouse."""

    def __init__(
        self,
        code: GuardrailCode,
        message: str,
        detail: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        rendered = f"{code.value}: {message}"
        if detail:
            rendered = f"{rendered} ({detail})"
        super().__init__(rendered)


class SqlExecutionError(SqlAgentError):
    """DuckDB rejected or could not execute a validated query."""


class QueryTimeoutError(SqlExecutionError):
    """A query exceeded the configured watchdog timeout (D15)."""


class LLMError(SqlAgentError):
    """The configured LLM backend failed (transport, missing model, ...)."""


class LLMProtocolError(LLMError):
    """The LLM returned content that does not satisfy the action protocol."""


class CassetteMiss(LLMError):
    """No recorded response matches the request (S22)."""


class WarehouseUnavailable(SqlAgentError):
    """The bundled warehouse is missing, corrupt or cannot be opened."""


class ConfigError(SqlAgentError):
    """Invalid or insecure configuration (S19/S26)."""
