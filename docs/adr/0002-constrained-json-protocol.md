# ADR-0002: Constrained JSON protocol instead of provider-native tool calling

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Eduardo Pacheco

## Context

The agent needs the model to choose between four actions (`final_sql`,
`lookup_values`, `clarify`, `refuse`) and to return a short plan. The default backend is
a small local model served by Ollama. Provider-native tool calling exists, but small
models frequently mis-emit native tool calls or invent tool names, and the exact prompt
format differs between backends. We also need identical prompts to replay
deterministically from recordings, and scripted fakes must exercise the same protocol.

Ollama 0.40.x supports JSON-schema-constrained decoding through the `format` field of
`/api/chat`, which can remove most syntax errors without any provider-specific tool
machinery.

## Decision

Define one flat JSON object, validated by a JSON Schema (and by a Pydantic model in the
application layer), with fields:

- `plan[]`: one to five short steps (at most 160 characters each).
- `action`: one of `final_sql`, `lookup_values`, `clarify`, `refuse`.
- `sql`, `lookup`, `message`: conditional fields required by the chosen action.

The same schema is passed to Ollama's `format` field, used by `ScriptedLLM` tests and
included in recorded cassettes. Invalid JSON or schema violations get one protocol retry,
then a graceful `FAILED` answer. The loop dispatches `lookup_values` itself; the model
never executes tools directly.

## Consequences

- Works identically across Ollama models and test fakes; no dependency on native tool
  calling support.
- The plan is a field of the same output instead of a second LLM call, saving a round
  trip and keeping latency lower.
- The prompt and schema are part of the cassette key, so protocol changes visibly
  invalidate recordings instead of silently changing behaviour.
- We give up automatic tool orchestration from the provider and must parse and validate
  every response ourselves. The schema is small and the validation is tested.
- A model that cannot follow JSON may need the one retry; after that the answer is a
  friendly failure rather than an exception.

## Alternatives considered

- **Provider-native tool calling:** rejected for cross-backend inconsistency, poor
  behaviour on small models and harder deterministic replay.
- **Free-form text plus regex extraction:** rejected as brittle and unsafe; it invites
  malformed SQL and ambiguous action selection.
- **Separate planning call:** rejected because it doubles latency and cost for a plan
  that only feeds the trace and UI.
