"""Agent tools: fixed-SQL value resolution against lookupable columns (S8).

``lookup_values`` is deliberately not model-written SQL: the tool validates the
column against the semantic layer whitelist and delegates to the warehouse
adapter's parameterised query.  Every returned value is rendered as an untrusted
``lookup`` block before it can enter a prompt (S18).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlagent.application.ports import WarehousePort
from sqlagent.domain.errors import SqlExecutionError
from sqlagent.domain.sanitize import DataSanitizer
from sqlagent.domain.semantic import SemanticLayer

MAX_LOOKUP_VALUES = 5


@dataclass(frozen=True, slots=True)
class LookupValuesResult:
    """Outcome of one ``lookup_values`` tool call (errors are values, not raises)."""

    ok: bool
    values: tuple[str, ...] = ()
    block: str = ""
    flags: int = 0
    error: str | None = None


class LookupValuesTool:
    """Resolve colloquial entity names against whitelisted lookupable columns."""

    name = "lookup_values"

    def __init__(
        self,
        warehouse: WarehousePort,
        semantic: SemanticLayer,
        *,
        sanitizer: DataSanitizer | None = None,
        max_values: int = MAX_LOOKUP_VALUES,
    ) -> None:
        self._warehouse = warehouse
        self._sanitizer = sanitizer or DataSanitizer()
        self._max_values = max(1, min(max_values, MAX_LOOKUP_VALUES))
        self._columns = {ref.casefold(): ref for ref in semantic.lookupable_columns()}

    @property
    def columns(self) -> tuple[str, ...]:
        """The whitelisted ``table.column`` references, in semantic-layer order."""

        return tuple(self._columns.values())

    def run(self, column: str, query: str, k: int = MAX_LOOKUP_VALUES) -> LookupValuesResult:
        """Return at most five sanitised candidates, or a tool error string."""

        canonical = self._columns.get(column.strip().casefold())
        if canonical is None:
            allowed = ", ".join(self.columns)
            return LookupValuesResult(
                ok=False,
                error=f"column {column!r} is not lookupable; choose one of: {allowed}",
            )
        text = query.strip()
        if not text:
            return LookupValuesResult(ok=False, error="lookup query must not be empty")

        limit = max(1, min(k, self._max_values))
        try:
            raw_values = self._warehouse.lookup_values(canonical, text, limit)
        except (SqlExecutionError, ValueError) as exc:
            return LookupValuesResult(ok=False, error=f"lookup failed: {exc}")
        values = tuple(dict.fromkeys(str(value) for value in raw_values))[:limit]
        rendered = self._sanitizer.render_block_result(list(values), "lookup")
        return LookupValuesResult(
            ok=True,
            values=values,
            block=rendered.text,
            flags=rendered.flags,
        )


__all__ = ["MAX_LOOKUP_VALUES", "LookupValuesResult", "LookupValuesTool"]
