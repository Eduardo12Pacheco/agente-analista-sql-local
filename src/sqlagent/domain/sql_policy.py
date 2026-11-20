"""SQL guardrail: a parse-don't-validate policy over a sqlglot AST (S16/D14).

The policy is a chain of responsibility.  Every rule either passes, mutates the
AST (only ``LimitRule``) or raises :class:`GuardrailViolation` with a stable
:class:`GuardrailCode`.  Successful validation returns a :class:`ValidatedQuery`
that cannot be constructed anywhere else; the warehouse port accepts only that
type, so "validated SQL" is a property of the type system rather than a
convention.

Defence in depth (ADR-0003): the prompt tells the model what it may do, this AST
policy rejects everything else, the DuckDB connection is read-only and locked,
and the result/time limits bound the blast radius of an expensive query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from sqlagent.domain.errors import GuardrailCode, GuardrailViolation

__all__ = [
    "ALLOWED_FUNCTIONS",
    "ALLOWED_NODE_TYPES",
    "CATALOG_DEFAULT",
    "WRITE_INTENT_CODES",
    "GuardrailCode",
    "GuardrailViolation",
    "SqlPolicy",
    "ValidatedQuery",
]

MAX_SQL_CHARS: Final = 4_000
MAX_NODES: Final = 1_500
MAX_DEPTH: Final = 6

CATALOG_DEFAULT: Final[frozenset[str]] = frozenset(
    {"buyers", "suppliers", "tenders", "awards", "contracts", "tender_items"}
)

#: D14: rejections that mean "you asked to write / reach the filesystem" and
#: therefore must be refused, never repaired.
WRITE_INTENT_CODES: Final[frozenset[GuardrailCode]] = frozenset(
    {
        GuardrailCode.NOT_SELECT,
        GuardrailCode.FORBIDDEN_NODE,
        GuardrailCode.TABLE_FUNCTION,
    }
)

#: D14 function allowlist.  ``exp.Anonymous`` nodes (functions sqlglot does not
#: type) are accepted only when their lower-cased name is in this set.
_ALLOWED_FUNCTION_NAMES: Final[tuple[str, ...]] = (
    "count",
    "sum",
    "avg",
    "min",
    "max",
    "median",
    "quantile_cont",
    "quantile_disc",
    "stddev",
    "stddev_samp",
    "stddev_pop",
    "var_samp",
    "var_pop",
    "mode",
    "arg_max",
    "arg_min",
    "bool_and",
    "bool_or",
    "string_agg",
    "list",
    "first",
    "last",
    "approx_count_distinct",
    "coalesce",
    "nullif",
    "ifnull",
    "round",
    "ceil",
    "ceiling",
    "floor",
    "abs",
    "sign",
    "sqrt",
    "power",
    "ln",
    "log10",
    "greatest",
    "least",
    "date_trunc",
    "date_part",
    "date_diff",
    "datediff",
    "date_add",
    "date_sub",
    "year",
    "month",
    "day",
    "quarter",
    "week",
    "dayofweek",
    "strftime",
    "make_date",
    "age",
    "lower",
    "upper",
    "trim",
    "ltrim",
    "rtrim",
    "length",
    "strlen",
    "substr",
    "substring",
    "replace",
    "concat",
    "concat_ws",
    "contains",
    "starts_with",
    "ends_with",
    "strip_accents",
    "lpad",
    "rpad",
    "left",
    "right",
    "regexp_matches",
    "row_number",
    "rank",
    "dense_rank",
    "percent_rank",
    "lag",
    "lead",
    "first_value",
    "last_value",
    "ntile",
    "cume_dist",
)
ALLOWED_FUNCTIONS: Final[frozenset[str]] = frozenset(_ALLOWED_FUNCTION_NAMES)


def _expression_classes(*names: str) -> frozenset[type[exp.Expr]]:
    """Resolve sqlglot classes once at import time (pinned-behaviour test guards upgrades)."""

    return frozenset(getattr(exp, name) for name in names)


#: Typed function/expression classes accepted by ``FunctionRule``.  Keep this
#: explicit: a class missing here is rejected even if sqlglot knows it.
ALLOWED_FUNCTION_CLASSES: Final[frozenset[type[exp.Expr]]] = _expression_classes(
    "Count",
    "Sum",
    "Avg",
    "Min",
    "Max",
    "Median",
    "PercentileCont",
    "PercentileDisc",
    "Stddev",
    "StddevSamp",
    "StddevPop",
    "Variance",
    "VariancePop",
    "Mode",
    "ArgMax",
    "ArgMin",
    "LogicalAnd",
    "LogicalOr",
    "GroupConcat",
    "ArrayAgg",
    "First",
    "Last",
    "ApproxDistinct",
    "Coalesce",
    "Nullif",
    "Round",
    "Ceil",
    "Floor",
    "Abs",
    "Sign",
    "Sqrt",
    "Pow",
    "Ln",
    "Log",
    "Greatest",
    "Least",
    "TimestampTrunc",
    "Extract",
    "DateDiff",
    "DateAdd",
    "DateSub",
    "DateFromParts",
    "Year",
    "Month",
    "Day",
    "Quarter",
    "Week",
    "DayOfWeek",
    "TimeToStr",
    "Lower",
    "Upper",
    "Trim",
    "Length",
    "Substring",
    "Replace",
    "Concat",
    "ConcatWs",
    "Contains",
    "StartsWith",
    "EndsWith",
    "Pad",
    "Left",
    "Right",
    "RegexpLike",
    "RowNumber",
    "Rank",
    "DenseRank",
    "PercentRank",
    "Lag",
    "Lead",
    "FirstValue",
    "LastValue",
    "Ntile",
    "CumeDist",
    "Case",
    "If",
    "Cast",
    "TryCast",
    "And",
    "Or",
    "Xor",
    "Exists",
)

#: Structural expression classes the policy understands.  Anything not listed is
#: rejected, which is what makes this an allowlist rather than a denylist.
_STRUCTURAL_CLASSES: Final[frozenset[type[exp.Expr]]] = _expression_classes(
    "Select",
    "From",
    "Where",
    "Group",
    "Having",
    "Order",
    "Ordered",
    "Limit",
    "Offset",
    "Qualify",
    "Join",
    "Table",
    "TableAlias",
    "Alias",
    "Column",
    "Identifier",
    "Literal",
    "Star",
    "Var",
    "Null",
    "Boolean",
    "Distinct",
    "CTE",
    "With",
    "Subquery",
    "Union",
    "Intersect",
    "Except",
    "Values",
    "Tuple",
    "DataType",
    "DataTypeParam",
    "Interval",
    "Window",
    "WithinGroup",
    "Filter",
    "Semicolon",
    "Block",
    "Paren",
    "Escape",
    "Array",
    "RawString",
    "Add",
    "Sub",
    "Mul",
    "Div",
    "Mod",
    "Neg",
    "EQ",
    "NEQ",
    "GT",
    "GTE",
    "LT",
    "LTE",
    "Not",
    "Is",
    "In",
    "Between",
    "Like",
    "ILike",
    "Unnest",
)

ALLOWED_NODE_TYPES: Final[frozenset[type[exp.Expr]]] = frozenset(
    _STRUCTURAL_CLASSES | ALLOWED_FUNCTION_CLASSES | {exp.Anonymous}
)

_DENIED_CLASS_NAMES: Final = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "Command",
    "Pragma",
    "Set",
    "Copy",
    "Attach",
    "Detach",
    "Use",
    "Transaction",
    "Commit",
    "Rollback",
    "Into",
    "Pivot",
    "Unpivot",
    "Lateral",
    "Unnest",
    "Show",
    "Describe",
    "Export",
    "Install",
    "Load",
)

DENIED_NODE_TYPES: Final[frozenset[type[exp.Expr]]] = frozenset(
    cls
    for name in _DENIED_CLASS_NAMES
    if (cls := getattr(exp, name, None)) is not None and issubclass(cls, exp.Expression)
)

_QUERY_TYPES: Final[tuple[type[exp.Expr], ...]] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
)
_ALLOWED_ROOTS: Final[tuple[type[exp.Expr], ...]] = (*_QUERY_TYPES, exp.With)
_SYSTEM_TABLE_PREFIXES: Final = ("duckdb_", "pg_", "sqlite_")
_SYSTEM_SCHEMAS: Final = frozenset({"information_schema", "pg_catalog", "duckdb"})

_VALIDATION_TOKEN: Final = object()


@dataclass(frozen=True, slots=True)
class ValidatedQuery:
    """A statement that passed every ``SqlPolicy`` rule.

    Only ``SqlPolicy.validate`` holds the module-private token required to build
    one; the warehouse port accepts nothing else.
    """

    sql: str
    tables: tuple[str, ...]
    original_sql: str
    limit_applied: int
    _validation_token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._validation_token is not _VALIDATION_TOKEN:
            raise TypeError("ValidatedQuery must be created by SqlPolicy.validate()")


@dataclass(slots=True)
class _ValidationContext:
    sql: str
    catalog: frozenset[str]
    max_rows: int
    max_sql_chars: int
    ast: exp.Expr | None = None
    cte_names: frozenset[str] = frozenset()
    tables: tuple[str, ...] = ()
    limit_applied: int = 0


class _Rule:
    """One link of the guardrail chain of responsibility."""

    def apply(self, context: _ValidationContext) -> None:  # pragma: no cover - protocol
        raise NotImplementedError


def _reject(code: GuardrailCode, message: str, detail: str | None = None) -> None:
    raise GuardrailViolation(code=code, message=message, detail=detail)


class LengthRule(_Rule):
    def apply(self, context: _ValidationContext) -> None:
        if len(context.sql) > context.max_sql_chars:
            _reject(
                GuardrailCode.TOO_LONG,
                f"SQL exceeds {context.max_sql_chars} characters",
                str(len(context.sql)),
            )


class ParseRule(_Rule):
    def apply(self, context: _ValidationContext) -> None:
        if not context.sql.strip():
            _reject(GuardrailCode.EMPTY, "SQL is empty")
        try:
            statements = sqlglot.parse(context.sql, read="duckdb")
        except SqlglotError as exc:
            _reject(GuardrailCode.PARSE_ERROR, "SQL cannot be parsed", str(exc).splitlines()[0])
        parsed = [
            statement
            for statement in statements
            if statement is not None and not isinstance(statement, exp.Semicolon)
        ]
        if not parsed:
            _reject(GuardrailCode.EMPTY, "SQL has no statement")
        if len(parsed) > 1:
            _reject(
                GuardrailCode.MULTI_STATEMENT,
                "Exactly one statement is allowed",
                f"found {len(parsed)}",
            )
        incomplete = [select for select in parsed[0].find_all(exp.Select) if not select.expressions]
        if incomplete:
            _reject(GuardrailCode.PARSE_ERROR, "SELECT is missing its projection")
        context.ast = parsed[0]


class RootRule(_Rule):
    def apply(self, context: _ValidationContext) -> None:
        ast = _ast(context)
        if not isinstance(ast, _ALLOWED_ROOTS):
            _reject(
                GuardrailCode.NOT_SELECT,
                "Only SELECT queries are allowed",
                type(ast).__name__,
            )
        if isinstance(ast, exp.With) and not isinstance(ast.this, _QUERY_TYPES):
            _reject(GuardrailCode.NOT_SELECT, "WITH must wrap a SELECT query")


class NodeRule(_Rule):
    def apply(self, context: _ValidationContext) -> None:
        ast = _ast(context)
        for node in ast.walk():
            node_type = type(node)
            if node_type is exp.Unnest and (
                _inside_cte(node) or _is_table_function_container(node)
            ):
                continue
            if node_type in DENIED_NODE_TYPES:
                _reject(
                    GuardrailCode.FORBIDDEN_NODE,
                    "Statement contains a forbidden node",
                    node_type.__name__,
                )
            if isinstance(node, exp.Func):
                # FunctionRule owns the (explicit) function allowlist; it also
                # lets TableRule report table-valued functions as TABLE_FUNCTION.
                continue
            if node_type not in ALLOWED_NODE_TYPES:
                _reject(
                    GuardrailCode.FORBIDDEN_NODE,
                    "Node class is not allowlisted",
                    node_type.__name__,
                )


class FunctionRule(_Rule):
    def apply(self, context: _ValidationContext) -> None:
        ast = _ast(context)
        for node in ast.walk():
            if not isinstance(node, exp.Func):
                continue
            if _is_table_function(node):
                continue
            if type(node) is exp.Anonymous:
                name = node.name.lower()
                if name not in ALLOWED_FUNCTIONS:
                    _reject(
                        GuardrailCode.FORBIDDEN_FUNCTION,
                        "Function is not allowlisted",
                        name or "<anonymous>",
                    )
                continue
            if not any(type(node) is cls for cls in ALLOWED_FUNCTION_CLASSES):
                _reject(
                    GuardrailCode.FORBIDDEN_FUNCTION,
                    "Function class is not allowlisted",
                    type(node).__name__,
                )


class TableRule(_Rule):
    def apply(self, context: _ValidationContext) -> None:
        ast = _ast(context)
        context.cte_names = frozenset(
            cte.alias.lower() for cte in ast.find_all(exp.CTE) if cte.alias
        )
        tables: set[str] = set()
        for table in ast.find_all(exp.Table):
            if not isinstance(table.this, exp.Identifier):
                _reject(
                    GuardrailCode.TABLE_FUNCTION,
                    "Table-valued functions are not allowed",
                    str(table.this)[:80],
                )
            schema = (table.db or "").lower()
            if table.catalog:
                _reject(
                    GuardrailCode.UNKNOWN_TABLE,
                    "Catalog-qualified tables are not allowed",
                    table.name,
                )
            if schema and schema not in {"main"}:
                _reject(
                    GuardrailCode.UNKNOWN_TABLE,
                    "Only the main schema is allowed",
                    schema,
                )
            name = table.name.lower()
            if name.startswith(_SYSTEM_TABLE_PREFIXES) or schema in _SYSTEM_SCHEMAS:
                _reject(
                    GuardrailCode.UNKNOWN_TABLE,
                    "System catalogs are not allowed",
                    table.name,
                )
            if name not in context.catalog and name not in context.cte_names:
                _reject(
                    GuardrailCode.UNKNOWN_TABLE,
                    "Table is not in the warehouse catalog",
                    table.name,
                )
            if name in context.catalog:
                tables.add(name)
        context.tables = tuple(sorted(tables))


class ComplexityRule(_Rule):
    def apply(self, context: _ValidationContext) -> None:
        ast = _ast(context)
        nodes = list(ast.walk())
        if len(nodes) > MAX_NODES:
            _reject(
                GuardrailCode.TOO_COMPLEX,
                f"SQL exceeds {MAX_NODES} AST nodes",
                str(len(nodes)),
            )
        depth = max(
            (_query_depth(node) for node in nodes if isinstance(node, _QUERY_TYPES)),
            default=0,
        )
        if depth > MAX_DEPTH:
            _reject(
                GuardrailCode.TOO_COMPLEX,
                f"SQL nests subqueries deeper than {MAX_DEPTH}",
                str(depth),
            )


class LimitRule(_Rule):
    def apply(self, context: _ValidationContext) -> None:
        ast = _ast(context)
        query = ast.this if isinstance(ast, exp.With) else ast
        if not isinstance(query, exp.Query):
            _reject(GuardrailCode.NOT_SELECT, "Top-level node is not a query")
        limit = query.args.get("limit")
        if limit is None:
            query.set("limit", exp.Limit(expression=exp.Literal.number(context.max_rows)))
            context.limit_applied = context.max_rows
            return
        expression = limit.expression
        existing = (
            int(expression.this.split(".")[0])
            if isinstance(expression, exp.Literal)
            and not expression.is_string
            and expression.this.isdigit()
            else None
        )
        if existing is None or existing > context.max_rows:
            limit.set("expression", exp.Literal.number(context.max_rows))
            context.limit_applied = context.max_rows
        else:
            context.limit_applied = existing


_RULES: Final[tuple[type[_Rule], ...]] = (
    LengthRule,
    ParseRule,
    RootRule,
    NodeRule,
    FunctionRule,
    TableRule,
    ComplexityRule,
    LimitRule,
)


class SqlPolicy:
    """Validate one read-only analytic SQL statement against the catalog (D14)."""

    def __init__(
        self,
        catalog_tables: frozenset[str] = CATALOG_DEFAULT,
        max_rows: int = 1_000,
        max_sql_chars: int = MAX_SQL_CHARS,
    ) -> None:
        if max_rows < 1:
            raise ValueError("max_rows must be positive")
        self.catalog_tables = frozenset(name.lower() for name in catalog_tables)
        self.max_rows = max_rows
        self.max_sql_chars = max_sql_chars
        self._rules: tuple[_Rule, ...] = tuple(rule() for rule in _RULES)

    def validate(self, sql: str) -> ValidatedQuery:
        context = _ValidationContext(
            sql=sql,
            catalog=self.catalog_tables,
            max_rows=self.max_rows,
            max_sql_chars=self.max_sql_chars,
        )
        for rule in self._rules:
            rule.apply(context)
        ast = _ast(context)
        rendered = ast.sql(dialect="duckdb", comments=False)
        return ValidatedQuery(
            sql=rendered,
            tables=context.tables,
            original_sql=sql,
            limit_applied=context.limit_applied,
            _validation_token=_VALIDATION_TOKEN,
        )


def _ast(context: _ValidationContext) -> exp.Expr:
    if context.ast is None:  # pragma: no cover - ParseRule guarantees this
        raise GuardrailViolation(GuardrailCode.PARSE_ERROR, "SQL was not parsed")
    return context.ast


def _inside_cte(node: exp.Expr) -> bool:
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.CTE):
            return True
        parent = parent.parent
    return False


def _is_table_function(node: exp.Func) -> bool:
    parent = node.parent
    return isinstance(parent, exp.Table) and parent.this is node


def _is_table_function_container(node: exp.Expr) -> bool:
    parent = node.parent
    return isinstance(parent, exp.Table) and parent.this is node


def _query_depth(node: exp.Expr) -> int:
    depth = 0
    parent = node.parent
    while parent is not None:
        if isinstance(parent, _QUERY_TYPES):
            depth += 1
        parent = parent.parent
    return depth
