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

## Scoring

The runner and metrics (execution accuracy, Wilson intervals, pair consistency,
latency/tokens, failure taxonomy) are implemented in T9; the benchmark model,
lock and gold-SQL acceptance suite in T8 are the stable input for that engine.
See `docs/EVAL.md` after T12 for measured results.
