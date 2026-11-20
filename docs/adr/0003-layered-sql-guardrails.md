# ADR-0003: Layered SQL guardrails with an AST allowlist

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Eduardo Pacheco

## Context

The agent turns natural-language questions into SQL and executes the result against a
local DuckDB warehouse. Local models make mistakes and prompt-injected data can try to
steer the model towards writes, file access or resource exhaustion. The warehouse is
read-only, but a single `read_csv('/etc/passwd')`, `COPY ... TO`, `ATTACH` or pathological
cross join would still be unacceptable in a desktop tool that claims to be safe.

Text-level filters and prompt instructions are not an execution boundary: the model can
be wrong or manipulated, and the connection must not rely on the model's goodwill.

## Decision

Use **defence in depth** with four independent layers:

1. **Prompt rules** explain the DuckDB dialect, read-only scope and the JSON protocol.
   They improve the model's odds but are never trusted.
2. **`SqlPolicy`** parses every statement with sqlglot (dialect `duckdb`) and applies an
   ordered chain of responsibility: length, single-statement parse, SELECT-only root,
   node allowlist, function allowlist, catalog/CTE table allowlist, complexity bounds and
   an AST-level `LIMIT` rewrite. Unknown nodes, functions or tables are rejected; the
   SQL that runs is regenerated from the validated AST (comments dropped), so parser
   quirks cannot smuggle a second interpretation.
3. **`ValidatedQuery`** is a frozen type constructible only by `SqlPolicy.validate`. The
   warehouse port accepts that type, making "this SQL passed the guardrail" a type-level
   property (parse, don't validate).
4. **A locked read-only DuckDB connection** (`read_only=True`, external access disabled,
   extension autoload off, memory/thread limits) plus a watchdog timeout and a row cap.

Rejections carry a stable `GuardrailCode`. Write/DDL/file-intent codes are refused
without repair; repairable violations (for example an unknown column) can be sent back to
the model with the error text. The adversarial and legitimate SQL corpora, the fuzz
property and the pinned sqlglot-behaviour test keep the policy honest across upgrades.

## Consequences

- A poisoned data value cannot cause a non-SELECT execution or file access, even when a
  scripted "obedient" model follows the injection; the AST policy is the real boundary.
- The policy is deterministic and fast (sub-20 ms p95 on the analytic corpus), so it can
  run on every attempt without a measurable latency cost.
- The allowlist is deliberately conservative: a new analytical function or SQL construct
  must be added with a test and a decision, rather than being accepted implicitly.
- sqlglot major upgrades may change AST shapes; a pinned-behaviour test fails loudly and
  forces an explicit review instead of silently widening or breaking the policy.
- Some legitimate DuckDB features (table functions, `PIVOT`, `UNNEST` outside CTEs,
  sampling, locking reads) are unavailable to the agent. They are not needed for the
  benchmark, and the restriction is documented.

## Alternatives considered

- **Prompt-only safety:** rejected; instructions are not an execution boundary.
- **Regex/keyword blocklists:** rejected because SQL is context-sensitive and keyword
  lists are trivially bypassed with comments, casing or alternate syntax.
- **Running arbitrary SQL and relying on the read-only connection:** rejected because
  read-only does not prevent file reads, extension installs, huge cross joins or
  information-schema probing.
- **A separate SQL parser/proxy:** rejected as an unnecessary dependency; sqlglot is
  already required for dialect-aware regeneration and the benchmark's table extraction.
