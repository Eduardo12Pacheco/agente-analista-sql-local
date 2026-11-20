# Evaluation

The evaluation engine scores the agent on **benchmark v1**, a versioned set of
72 questions over the bundled SERCOP 2021 warehouse. It measures execution
accuracy (EX), not text similarity: a prediction is correct when its result set
matches the gold SQL result under the rules in D19 of the project plan.

## Benchmark v1

The benchmark lives in `src/sqlagent/resources/benchmark/v1/questions.yaml` and
is loaded by `YamlBenchmarkRepository` into the pydantic `Benchmark` model. The
document is a flat YAML list of 72 items; each item contains:

| Field | Meaning |
|---|---|
| `id` | Sequential identifier, `q001`…`q072` |
| `category` | One of the nine D19 categories plus `unanswerable_ambiguous` and `adversarial_safety` |
| `difficulty` | `easy`, `medium` or `hard` |
| `lang` | `es` or `en` |
| `question` | The user-facing question |
| `gold_sql` | DuckDB SQL for answerable items, `null` otherwise |
| `pair_id` | `p01`…`p12` for ES↔EN pairs that share identical gold SQL, otherwise `null` |
| `expect` | `answer`, `clarification`, `unanswerable` or `refusal` |
| `tags` | Free-form labels (`ranking`, `anchor`, `pair`, …) |

### Composition

| Dimension | Quotas |
|---|---|
| Answerable categories | aggregation 8, filtering 8, join 10, grouping/top-k 10, temporal 7, ratio/percentage 6, subquery/CTE/window 6, entity resolution 5 |
| Non-answerable | unanswerable/ambiguous 6, adversarial/safety 6 |
| Language | 38 ES / 34 EN |
| Difficulty | easy 24 / medium 30 / hard 18 |
| Expectations | answer 60, clarification 3, unanswerable 3, refusal 6 |
| Bilingual pairs | 12 ES↔EN pairs sharing identical gold SQL |

D19's difficulty line states “24 easy, 30 medium, 18 hard”, which sums to 72;
because the benchmark also has 12 non-answerable items, the only self-consistent
reading is that the split covers the complete benchmark. Non-answerable items
therefore carry a difficulty label too, while all other quotas apply per category
and language exactly as in D19.

### Gold SQL rules

- DuckDB dialect over the six D7 tables only; every statement passes
  `SqlPolicy` (single read-only `SELECT`/`WITH…SELECT`, allowlisted nodes,
  functions and tables, LIMIT ≤ 1,000).
- Deterministic: no `current_date`, `current_timestamp`, `now()`, `random()` or
  `uuid()`; ranking questions have a top-level `ORDER BY` with a unique
  tie-break and `LIMIT` ≤ 200.
- Returns between 1 and 200 rows and produces identical rows on two consecutive
  executions.
- Natural-person suppliers are never referenced by name or pseudonym; entity
  resolution uses real public-buyer names verified against the bundled data
  (IESS, CELEC, BanEcuador, Contraloría, Municipio de Machala).
- Few-shot questions and SQL in `resources/fewshots.yaml` are disjoint from the
  benchmark after whitespace/case normalisation.

`tests/integration/test_benchmark_v1.py` enforces all of the above, plus BM25
table recall ≥ 0.95 over the gold SQL table sets. The benchmark currently scores
100% table recall.

## Lock file

`benchmark.lock.json` pins the SHA-256 of `questions.yaml` and of the warehouse
`MANIFEST.json`, together with `n` and the composition counts. Regenerate it
after editing the questions or rebuilding the Parquet bundle:

```bash
uv run python scripts/lock_benchmark.py
```

Use `--check` (exit 2 on drift) in CI or before recording new model outputs.
A changed question file or warehouse invalidates recorded cassettes by design
(D18), so the lock and the cassette freshness test move together.

## Evaluation engine

`sqlagent eval` runs `RunEvaluation`, which filters the benchmark, executes every
gold SQL on the same read-only warehouse, runs the agent single-turn with
narration disabled by default, and scores each answer under the D19 rules.
Gold SQL is validated by `SqlPolicy` before execution, so the evaluation never
bypasses the guardrails.

```bash
# offline replay of the committed recordings
uv run sqlagent eval --llm replay

# live Ollama run, recording the cassette
uv run sqlagent eval --llm ollama --model qwen3:8b --record

# ablations
uv run sqlagent eval --llm ollama --max-repairs 0 --out eval/reports/no-repair
uv run sqlagent eval --llm ollama --no-retrieval --out eval/reports/no-retrieval

# regression gate against a baseline summary
uv run sqlagent eval --llm replay --compare eval/baseline.json
```

### Execution accuracy (EX)

An item is EX-correct when the answer has `status=ok`, an executed SQL statement,
and its rows match the gold rows positionally by column (names ignored):

- ordered comparison when the gold SQL has a top-level `ORDER BY`, otherwise a
  row multiset;
- floats within `max(1e-6·max(|a|,|b|), 0.01)`; `NULL == NULL`; dates as ISO
  strings; extra or missing columns are a mismatch;
- predicted rows are the documented 1,000-row cap; gold items return ≤ 200 rows.

Non-answerable items are scored against their expectation: `clarification` needs
`status=clarification`; `unanswerable` accepts `clarification` or `refused`
without execution; `refusal` needs `status=refused`.

### Metrics

`summary.json` (schema `sqlagent.eval-summary/v1`) contains:

| Metric | Definition |
|---|---|
| `overall.ex` + Wilson 95% CI | EX over the 60 answerable items |
| `overall.valid_sql_rate` | answerable items that executed a policy-valid SQL |
| `overall.first_attempt_ex` | answerable items correct with an error-free first attempt |
| `overall.repair_uplift` | `ex - first_attempt_ex` |
| `overall.refusal_acc` | refusal items answered with `refused` |
| `overall.clarification_acc` / `unanswerable_acc` | expectation accuracy for those groups |
| `overall.pair_consistency` | pairs with both languages correct among pairs where at least one is |
| `overall.retrieval_table_recall` | mean share of gold tables retrieved by BM25 |
| `overall.mean_attempts` | mean SQL attempts per answerable item |
| `overall.latency_ms` | wall-clock per question: mean, nearest-rank p50/p95 |
| `overall.tokens` | prompt/completion totals and per-question means |
| `by_category`, `by_language`, `by_difficulty` | EX, Wilson CI and expectation accuracy per group |
| `failure_taxonomy` | `protocol_error`, `guardrail_block`, `execution_error`, `wrong_tables`, `wrong_result`, `refusal_mismatch`, `timeout` |

For non-answerable categories `by_category.*.ex` is the expectation accuracy,
because EX is only defined for answerable items; this keeps the D20 gate able to
compare every category. `environment` records OS, CPU, Python, optional
`nvidia-smi` GPU line, SQLagent version and the warehouse manifest hash.
`config` records narration/retrieval, repair budget, sampling options and the
benchmark prompt version.

### Artifacts

Every run writes exactly four files to `--out` (default
`eval/reports/<UTC timestamp>-<model-slug>/`):

| File | Contents |
|---|---|
| `summary.json` | versioned document above, deterministic for fixed run id/timestamp/clock |
| `results.jsonl` | one compact JSON object per item |
| `report.md` | human summary, breakdowns, failure table with predicted vs gold SQL |
| `report.html` | self-contained report: inline SVG charts, light/dark CSS, no scripts |

The HTML report contains no external requests; the only external URLs are the
SERCOP source and CC BY 3.0 EC licence attribution links. All question text and
SQL is escaped.

### Regression gate

`--compare BASELINE` implements D20: it compares `overall.ex`,
`overall.refusal_acc` and every `by_category.*.ex` shared by both documents. A
metric fails when `current < baseline - max_drop` (default `0.0`); the CLI prints
a `REGRESSION <metric>: baseline -> current` line for each failure and exits 1.
Improvements are printed as hints to refresh the baseline. Categories missing
from either side (for example with `--limit`) are skipped rather than compared to
zero. A stale cassette exits 4 with the `--record` hint; benchmark lock drift and
unreadable baselines exit 2.

### Determinism and performance

The runner accepts an injectable clock, so tests produce byte-identical
`summary.json` documents for the same run metadata and item answers. Real runs
record the wall clock. The `OracleLLM` test backend (gold SQL) scores 60/60 on
the answerable items in well under the 60 s replay budget asserted by
`tests/integration/test_eval_pipeline.py`.

### Current results

No model results are quoted here until T12 records the real `qwen3:8b` and
`qwen2.5-coder:7b` runs in Docker Ollama on the owner's machine. The reports and
baseline committed in T12 are the only source for the README metrics table.
