# ADR-0006: Evaluation methodology, cassettes and the CI regression gate

## Context

The repository must prove its agent quality with a reproducible measurement, not
with hand-picked examples.  The measurement has to run offline in CI, be stable
enough to gate every push, and still reflect real model behaviour when a local
Ollama model is available.  Options considered were a small smoke suite
(cheap but not credible), an LLM-as-a-judge score (non-deterministic, expensive
and hard to gate), or execution accuracy against a versioned benchmark with
recorded model outputs.

## Decision

Use **execution accuracy (EX)** on the 72-item benchmark v1 as the primary
metric.  A prediction is correct when its result rows match the gold SQL result
under D19 (ordered only when the gold SQL has a top-level `ORDER BY`, multiset
otherwise, with the documented float tolerance).  The engine also reports
Wilson 95% confidence intervals, valid-SQL rate, first-attempt EX, repair uplift,
refusal/clarification/unanswerable accuracy, ES↔EN pair consistency, retrieval
table recall, latency and token usage, and an automatic failure taxonomy.

Runs write four artifacts (`summary.json`, `results.jsonl`, `report.md`,
`report.html`); the HTML report is self-contained with inline SVG charts.  The
regression gate compares `overall.ex`, `overall.refusal_acc` and every
`by_category.*.ex` against a committed baseline and fails when a metric drops by
more than `--max-drop` (default 0).

Live model outputs are recorded as cassettes keyed by the SHA-256 of the
canonical request and replayed offline.  Cassettes store only a digest, a
200-character prompt preview and the response metadata, never the full prompt.
A stale cassette is a first-class failure (exit 4), and the prompt, semantic
layer and warehouse are frozen after the recording task (D18).  The evaluation
runner accepts an injectable clock so tests can prove byte-identical summaries
for identical inputs; the production path records wall-clock latency.

## Consequences

* CI can score the full benchmark offline in well under a minute and fail a
  regression without a GPU or network access.
* Numbers in the README are generated from `summary.json`, never typed by hand;
  the harness's own correctness is proven by an `OracleLLM` that scores 100% and
  by a sabotaged backend that must trip the gate.
* Recorded outputs are a single deterministic run on one machine, not a claim of
  general text-to-SQL accuracy; the benchmark is small (n = 72) and the
  confidence intervals are wide.  This limitation is documented in the README.
* Any change to prompts, retrieval, sanitisation or the warehouse invalidates the
  cassettes; the freshness test makes that breakage loud instead of silent.
* Non-answerable categories use expectation accuracy in `by_category.*.ex` so the
  gate can compare every category; the distinction is documented in
  `docs/EVAL.md`.

## Alternatives considered

* **LLM-as-a-judge**: rejects because a second model adds nondeterminism, cost and
  a dependency that contradicts the local-first, zero-key constraint.
* **Text similarity (BLEU/ROUGE) against gold SQL**: rejects because different
  correct SQL formulations would be penalised and the metric is not meaningful
  for analytical answers.
* **A tiny smoke suite**: rejects because it cannot detect category-level
  regressions or support the published per-category/language breakdowns.
* **Live Ollama on every CI push**: rejects because CI has no GPU/model and the
  result would be slow, expensive and nondeterministic; record/replay gives the
  same regression signal while keeping the live measurement reproducible.
