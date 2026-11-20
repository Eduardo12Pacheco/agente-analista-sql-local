"""Server-side SQL syntax highlighting (S29).

Highlighting happens on the server with the same sqlglot tokenizer used by the
validator, so the browser never needs a highlighter and every token is escaped
before it reaches the page.  Untrusted literals are escaped even when tokenizing
fails, which keeps the XSS boundary in one place.
"""

# ruff: noqa: S704 - every token is escaped before it is wrapped in Markup.

from __future__ import annotations

from html import escape

from markupsafe import Markup
from sqlglot.tokens import Tokenizer, TokenType  # type: ignore[attr-defined]

_KEYWORDS = frozenset(
    {
        "AGGREGATE",
        "ALL",
        "AND",
        "ANY",
        "AS",
        "ASC",
        "BETWEEN",
        "BY",
        "CASE",
        "CAST",
        "CROSS",
        "CURRENT",
        "CURRENT_DATE",
        "CURRENT_TIMESTAMP",
        "DESC",
        "DISTINCT",
        "ELSE",
        "END",
        "ESCAPE",
        "EXCEPT",
        "EXISTS",
        "FALSE",
        "FETCH",
        "FIRST",
        "FOLLOWING",
        "FOR",
        "FROM",
        "FULL",
        "GROUP",
        "GROUP_BY",
        "HAVING",
        "ILIKE",
        "IN",
        "INNER",
        "INTERSECT",
        "INTERVAL",
        "INTO",
        "IS",
        "JOIN",
        "LAST",
        "LATERAL",
        "LEFT",
        "LIKE",
        "LIMIT",
        "NATURAL",
        "NOT",
        "NULL",
        "NULLS",
        "OFFSET",
        "ON",
        "OR",
        "ORDER",
        "ORDER_BY",
        "OUTER",
        "OVER",
        "PARTITION",
        "PARTITION_BY",
        "PRECEDING",
        "QUALIFY",
        "RANGE",
        "RECURSIVE",
        "RIGHT",
        "ROWS",
        "SELECT",
        "SEMI",
        "SIMILAR",
        "TABLE",
        "THEN",
        "TRUE",
        "UNBOUNDED",
        "UNION",
        "UNIQUE",
        "VALUES",
        "WHEN",
        "WHERE",
        "WINDOW",
        "WITH",
    }
)

_TOKEN_CLASS: dict[TokenType, str] = {
    TokenType.STRING: "tok-str",
    TokenType.NUMBER: "tok-num",
    TokenType.BOOLEAN: "tok-num",
    TokenType.NULL: "tok-kw",
}


def _token_class(token_type: TokenType, name: str, next_type: TokenType | None) -> str | None:
    if token_type is TokenType.VAR:
        return "tok-fn" if next_type is TokenType.L_PAREN else "tok-id"
    if token_type in _TOKEN_CLASS:
        return _TOKEN_CLASS[token_type]
    if name in _KEYWORDS:
        return "tok-kw"
    if token_type.name in {"EQ", "NEQ", "GT", "GTE", "LT", "LTE", "PLUS", "DASH", "STAR", "SLASH"}:
        return "tok-op"
    if token_type.name in {"COMMA", "DOT", "L_PAREN", "R_PAREN", "SEMICOLON", "COLON"}:
        return "tok-punct"
    return None


def highlight_sql(sql: str) -> Markup:
    """Return escaped HTML with ``tok-*`` spans for one SQL string."""

    if not sql:
        return Markup("")
    if not sql.strip():
        return Markup(escape(sql, quote=False))
    try:
        tokens = Tokenizer(dialect="duckdb").tokenize(sql)
    except Exception:  # sqlglot can raise on arbitrary text; display it verbatim
        return Markup(escape(sql, quote=False))

    parts: list[str] = []
    cursor = 0
    for index, token in enumerate(tokens):
        start = max(0, int(token.start))
        end = int(token.end) + 1
        if start > cursor:
            parts.append(escape(sql[cursor:start], quote=False))
        next_type = tokens[index + 1].token_type if index + 1 < len(tokens) else None
        css_class = _token_class(token.token_type, token.token_type.name, next_type)
        rendered = escape(sql[start:end], quote=False)
        if css_class is not None:
            parts.append(f'<span class="{css_class}">{rendered}</span>')
        else:
            parts.append(rendered)
        cursor = max(cursor, end)
    if cursor < len(sql):
        parts.append(escape(sql[cursor:], quote=False))
    return Markup("".join(parts))


__all__ = ["highlight_sql"]
