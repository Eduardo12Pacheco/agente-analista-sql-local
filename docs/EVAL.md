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

### Results (real Ollama in Docker, 2026-11-20)

The benchmark was measured live through Docker Ollama on the owner's RTX 4060
(8,188 MiB): image `ollama/ollama:0.40.16`, container `ollama-sqlagent`, host URL
`127.0.0.1:11435`, 100% GPU offload. Both models ran with the same configuration
(temperature 0, seed 42, `num_ctx=8192`, `think=false`, narration disabled), and
the whole output of each run is committed under `eval/reports/`.

#### Model selection

| Model | Records | EX (60 answerable) | Wilson 95% CI | Valid SQL |
|---|---|---:|---|---:|
| `qwen2.5-coder:7b` (default) | `dae161e2…4364` | 63.3% | [50.7%, 74.4%] | 91.7% |
| `qwen3:8b` | `500a1f06…8b41` | 61.7% | [49.0%, 72.9%] | 100.0% |

D10 selects the model with the higher overall EX, so `qwen2.5-coder:7b` (63.3%)
is the default and its cassette ships in the wheel; `qwen3:8b` (61.7%) keeps its
cassette in `eval/recordings-extra/qwen3-8b/` for reproducibility (excluded from
the wheel). The two confidence intervals overlap, so this is a small, noisy
difference on n = 60 answerable items, not a claim of general superiority.

#### Default model, full run

| Metric | Result |
|---|---|
| Execution accuracy (EX) | 63.3% [50.7%, 74.4%] |
| Valid SQL rate | 91.7% |
| First-attempt EX | 63.3% |
| Repair uplift | +0.0 pts |
| Refusal accuracy | 100.0% |
| Latency p50 / p95 | 2455 ms / 8760 ms |
| Tokens per question | 3482 prompt / 93 completion |

Model `qwen2.5-coder:7b` (digest `dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364`) on NVIDIA GeForce RTX 4060, 8188 MiB, Linux-7.3.3-1-cachyos-x86_64-with-glibc2.44; run `20261120T130728Z-qwen2.5-coder-7b` on 2026-11-20T13:07:28+00:00; n = 72.

#### Ablations (default model only)

`--max-repairs 0` disables the repair loop; `--no-retrieval` sends all six tables
instead of the BM25 selection (D13). Ablation runs were not recorded to cassette.

| Configuration | EX | Valid SQL | Mean attempts |
|---|---:|---:|---:|
| retrieval + repair (default) | 63.3% | 91.7% | 1.18 |
| no repair | 63.3% | 90.0% | 1.00 |
| no retrieval | 68.3% | 95.0% | 1.12 |

Measured on this run, the repair loop changed valid-SQL rate (91.7% vs 90.0%) but
not execution accuracy (repair uplift 0.0 pts), and disabling retrieval raised EX
by 5.0 points (68.3% vs 63.3%) while sending more prompt tokens. This is an
honest, single-run result: the retrieval ablation is reported as measured, not
as the expected direction. It motivates future retrieval tuning but is outside
the frozen scope of v0.1.0.

#### Failure analysis

Failure taxonomy for the default model: `wrong_result` 14, `execution_error` 6,
`refusal_mismatch` 3, `wrong_tables` 2. The three largest modes, with concrete
items from `eval/reports/latest/report.md`:

1. **`wrong_result` (14).** The SQL is valid and executes, but the answer is
   wrong. q004 counts public works with `procurement_type = 'works'` instead of
   `category = 'works'`; q006 returns an extra `supplier_id` column, so the
   result shape differs from the gold answer even though the ranking is close.
2. **`execution_error` (6).** Three attempts produced no executable SQL and the
   agent ended `failed`. q005 (top provinces by tender count) and q009 (largest
   buyer per province) are join/window questions where the model never produced
   a statement accepted by the validator and the database.
3. **`refusal_mismatch` (3).** The agent answered when it should have clarified or
   refused. q012 (“Muéstrame el mejor proveedor”) picked a ranking metric instead
   of asking for the metric; q068 (“phone numbers of the suppliers”) returned the
   supplier table instead of refusing a non-modelled, privacy-sensitive field.

Category weaknesses are concentrated: `subquery_cte_window` 0/6 and
`entity_resolution` 0/5. Entity-resolution failures are exact case-sensitive name
matches (for example `'CELEC'` or `'Contraloría'` instead of the canonical
`CORPORACION ELECTRICA DEL ECUADOR CELEC EP` and `CONTRALORIA GENERAL DEL
ESTADO`), which is exactly the gap the `lookup_values` tool exists to close but
the model did not call. `clarification_acc` is 33.3% and `unanswerable_acc`
66.7%.

#### Provenance and limits

Hardware, Ollama version, image tag, model digests and run ids are recorded in
each summary's `environment`/`model` sections and in the report headers. This is
one warehouse, one benchmark (n = 72, wide CIs for n = 60 answerable items) and
one stochastic-free run per configuration on one machine; recorded outputs are
a single sample, not an average over seeds. Spanish retrieval is lexical (BM25
over the semantic layer). The committed `eval/baseline.json` is the default
model's full-run summary; `uv run sqlagent eval --llm replay --compare
eval/baseline.json` reproduces its EX offline, and
`tests/integration/test_recordings_fresh.py` replays the whole benchmark from the
committed cassette (a `CassetteMiss` means the prompt freeze was broken).
