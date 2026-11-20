# ADR-0009: Prompt-injection handling for untrusted data values

- **Status:** Accepted
- **Date:** 2026-11-20
- **Deciders:** Eduardo Pacheco

## Context

The SERCOP warehouse contains free-text fields (tender descriptions, supplier names,
item descriptions) written by external parties. Any of them can contain instructions
aimed at the model: "ignore previous instructions", a fake block terminator, bidi text
that hides content, or an XSS payload intended for the web UI. The agent feeds some of
these values back into prompts for narration and value lookup, so the data channel and
the instruction channel must be separated deliberately.

The real execution boundary is the SQL validator (ADR-0003): data must never be able to
produce new SQL. But the model can still be confused into leaking its prompt, narrating
an injected instruction as fact, or asking for extra tool calls. The trace and the UI
must make injection attempts visible without destroying evidence.

## Decision

Treat every database value as hostile text and route it through `DataSanitizer`:

1. Instructions live only in the `system` message; the user question is a `user`
   message; database-derived text appears only inside delimited data blocks.
2. Blocks are `<<DATA nonce=<8 hex> kind=<rows|lookup>>>`, a JSON payload and
   `<<END DATA nonce=<8 hex>>>`. The nonce is the SHA-256 of the payload, so an attacker
   cannot pre-embed a valid terminator; any `<<END DATA` or `<<DATA` inside a cell is
   neutralised. Rendering is deterministic, which keeps cassettes replayable.
3. Strip C0/C1 controls (except newline and tab), bidi overrides, zero-width characters
   and the BOM.
4. Truncate cells to 200 characters (including the flag marker) and payloads to 20 rows
   for narration and 10 values for lookups.
5. Flag, do not delete, cells matching the ES/EN injection patterns by appending
   `⟦flagged⟧` and counting the match. The count is exposed in the agent trace and the UI
   shows a badge; deleting the text would hide the attempt and change what the model sees
   in ways that are harder to explain.
6. The agent never executes text derived from data: SQL only comes from the
   `final_sql`/repair actions and always passes `SqlPolicy` before execution.
7. The web UI autoescapes every value (CSP `default-src 'self'`); XSS payloads are
   displayed as text, never executed.

## Consequences

- A poisoned row can at worst influence the wording of the answer, and the attempt is
  visible in the trace; it cannot change the SQL shape, trigger extra tool calls beyond
  the hard limits, or alter the output schema.
- Deterministic rendering keeps the recorded-output regression gate meaningful: the same
  warehouse rows produce the same prompt bytes.
- Truncation and row caps bound prompt size and cost, at the price of the model not
  seeing every row of a large result. Narration is a summary, not an exhaustive report.
- Pattern flagging is heuristic and intentionally conservative; false positives are
  possible (the marker is visible and the original text is retained). The validator, not
  the flagger, remains the security boundary.
- The nonce is a content hash, not a secret. It prevents delimiter forgery, not
  deliberate collision attacks, which are irrelevant to this local tool.

## Alternatives considered

- **Trusting the model to ignore data instructions:** rejected; this is the exact attack
  the feature must withstand.
- **Escaping/removing all punctuation or instruction-like words:** rejected because it
  destroys legitimate Spanish text and hides attacks instead of surfacing them.
- **Separate LLM call to classify every value:** rejected as slow, expensive and
  unreliable on a local 7–8B model; a deterministic sanitiser is testable and auditable.
- **HTML escaping inside the sanitiser:** rejected because the sanitiser feeds prompts,
  not HTML. The template layer owns HTML escaping and has its own XSS test.
