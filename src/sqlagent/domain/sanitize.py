"""Prompt-injection-safe rendering of untrusted database values (S18/D16).

Every value that comes out of the warehouse is treated as hostile text.  The
sanitiser strips control/bidi/zero-width characters, truncates cells and rows,
neutralises delimiter look-alikes, flags known injection patterns without
deleting them, and wraps the result in a block whose terminator nonce is the
SHA-256 of the content.  The block format is deterministic, so replaying the
same rows produces byte-identical prompts (a prerequisite for cassettes, D18).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

__all__ = [
    "FLAG_MARKER",
    "FLAG_PATTERNS",
    "MAX_CELL_CHARS",
    "MAX_LOOKUP_ROWS",
    "MAX_ROWS",
    "BlockKind",
    "DataSanitizer",
    "SanitizedBlock",
    "SanitizedRows",
]

BlockKind = Literal["rows", "lookup"]

MAX_CELL_CHARS: Final = 200
MAX_ROWS: Final = 20
MAX_LOOKUP_ROWS: Final = 10
FLAG_MARKER: Final = "⟦flagged⟧"

#: ES/EN prompt-injection patterns (D16 §5).  They are flagged, never deleted:
#: the validator -- not text filtering -- is the real execution boundary.
FLAG_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"ignore\s+(?:(?:all|any|previous|prior)\s+)+instructions",
        r"disregard\s+(?:(?:all|any|previous|prior)\s+)+instructions",
        r"ignora\s+(?:(?:todas|las)\s+)*instrucciones",
        r"olvida\s+(?:(?:todas|las)\s+)*instrucciones",
        r"system\s+prompt",
        r"prompt\s+del\s+sistema",
        r"you\s+are\s+now",
        r"ahora\s+eres",
        r"<\|im_start\|>",
        r"\[INST\]",
        r"BEGIN\s+SYSTEM",
        r"role:\s*system",
        r"drop\s+table",
        r"delete\s+from",
        r"reveal\s+.*(key|password|token)",
        r"ejecuta(r)?\s+(el|la)\s+siguiente",
        r"<<\s*(END[_ ]DATA|DATA)",
    )
)

_CONTROL_AND_INVISIBLE = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\u200b-\u200f\u2060\ufeff]"
)
_END_DELIMITER = re.compile(r"<<\s*END\s+DATA", re.IGNORECASE)
_START_DELIMITER = re.compile(r"<<\s*DATA(?=\s|>)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SanitizedRows:
    """Sanitised cells and the number of injection-pattern matches."""

    rows: tuple[tuple[str, ...], ...]
    flags: int


@dataclass(frozen=True, slots=True)
class SanitizedBlock:
    """Rendered prompt block plus its flag count (for the agent trace)."""

    text: str
    flags: int


class DataSanitizer:
    """Stateless renderer of untrusted rows/values as delimited JSON blocks."""

    def clean_cell(self, value: Any, *, max_chars: int = MAX_CELL_CHARS) -> str:
        """Normalise one cell: stringify, strip invisibles, neutralise, truncate."""

        text = _stringify(value)
        text = _CONTROL_AND_INVISIBLE.sub("", text)
        text = _END_DELIMITER.sub("<<END_DATA_NEUTRALISED", text)
        text = _START_DELIMITER.sub("<<DATA_NEUTRALISED", text)
        return text[:max_chars]

    def flag_cell(self, cell: str) -> tuple[str, bool]:
        """Return the cell (with marker) and whether it matched an injection pattern."""

        if any(pattern.search(cell) for pattern in FLAG_PATTERNS):
            return f"{cell}{FLAG_MARKER}", True
        return cell, False

    def sanitize_rows(
        self, rows: Sequence[Sequence[Any]], *, max_rows: int = MAX_ROWS
    ) -> SanitizedRows:
        sanitized: list[tuple[str, ...]] = []
        flags = 0
        for row in rows[:max_rows]:
            cells: list[str] = []
            for value in row:
                cell, flagged = self._sanitize_cell(value)
                flags += int(flagged)
                cells.append(cell)
            sanitized.append(tuple(cells))
        return SanitizedRows(rows=tuple(sanitized), flags=flags)

    def sanitize_values(
        self, values: Sequence[Any], *, max_rows: int = MAX_LOOKUP_ROWS
    ) -> SanitizedRows:
        return self.sanitize_rows([[value] for value in values[:max_rows]], max_rows=max_rows)

    def render_block(
        self,
        rows: Sequence[Sequence[Any]] | Sequence[Any],
        kind: BlockKind = "rows",
    ) -> str:
        """Render the block text for a prompt (D16 §2)."""

        return self.render_block_result(rows, kind).text

    def render_block_result(
        self,
        rows: Sequence[Sequence[Any]] | Sequence[Any],
        kind: BlockKind = "rows",
    ) -> SanitizedBlock:
        """Render the block and report how many cells matched injection patterns."""

        max_rows = MAX_LOOKUP_ROWS if kind == "lookup" else MAX_ROWS
        payload = _coerce_rows(rows, kind)
        sanitized = self.sanitize_rows(payload, max_rows=max_rows)
        if kind == "lookup":
            values: list[Any] = [row[0] for row in sanitized.rows]
        else:
            values = [list(row) for row in sanitized.rows]
        content = json.dumps(values, ensure_ascii=False)
        nonce = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
        text = f"<<DATA nonce={nonce} kind={kind}>>\n{content}\n<<END DATA nonce={nonce}>>"
        return SanitizedBlock(text=text, flags=sanitized.flags)

    def _sanitize_cell(self, value: Any) -> tuple[str, bool]:
        text = self.clean_cell(value)
        matched = any(pattern.search(text) for pattern in FLAG_PATTERNS)
        if not matched:
            return text, False
        budget = max(MAX_CELL_CHARS - len(FLAG_MARKER), 0)
        return f"{text[:budget]}{FLAG_MARKER}", True


def _stringify(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _coerce_rows(
    rows: Sequence[Sequence[Any]] | Sequence[Any], kind: BlockKind
) -> Sequence[Sequence[Any]]:
    if kind == "lookup":
        return [value if isinstance(value, (list, tuple)) else [value] for value in rows]
    coerced: list[Sequence[Any]] = []
    for row in rows:
        if isinstance(row, (list, tuple)):
            coerced.append(row)
        else:
            coerced.append([row])
    return coerced
