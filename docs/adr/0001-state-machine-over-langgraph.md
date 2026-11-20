# ADR-0001: A plain Python state machine instead of LangGraph

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Eduardo Pacheco

## Context

The analyst agent is an explicit, bounded workflow: understand the question, retrieve
schema context, generate SQL, validate it, execute it, repair up to two times, choose a
chart and narrate. It has ten phases, two small loops and hard limits on tool calls,
repairs and total LLM calls. The workflow must be deterministic under test with scripted
LLM outputs, stream phase events to the web UI, and produce a typed trace that the
evaluation harness can score.

LangGraph 1.2.24 was the obvious alternative, but it pulls `langchain-core` 1.8.4 and a
transitive dependency tree. That tree would dominate install size and supply-chain
surface for a local-first tool, and its abstractions would still need custom code for
the limits and typed trace we require.

## Decision

Implement the agent as a plain Python state machine in
`src/sqlagent/application/agent/`. A handler table maps each `Phase` to a function; the
machine owns the explicit counters (`tool_calls <= 3`, `repairs <= 2`, one protocol
retry per LLM call, a hard cap of 12 LLM calls per question) and emits typed
`AgentEvent`s. The graph is documented with the Mermaid state diagram in
`docs/ARCHITECTURE.md`.

## Consequences

- Zero runtime dependency beyond the small, audited set in `pyproject.toml`.
- Tests can drive every branch with `ScriptedLLM` and assert exact call counts, which
  makes termination and limit properties cheap to verify.
- Phase events, traces and error mapping are first-class rather than framework
  callbacks.
- We forgo LangGraph's checkpointing, visual graph tooling and ecosystem integrations.
  This app is single-turn with one previous turn of memory, so checkpointing is not a
  requirement. If multi-step durable workflows ever become necessary, the handler table
  is a contained module to replace.

## Alternatives considered

- **LangGraph 1.2.24:** rejected for the `langchain-core` 1.8.4 transitive tree,
  install weight and indirection, against a ten-state graph.
- **Ad-hoc nested loops:** rejected because branch coverage, bounds and trace semantics
  are hard to prove; a handler table keeps them explicit.
- **A generic workflow engine (Temporal, Prefect):** rejected as server-oriented and
  incompatible with the local-first, no-servers constraint.
