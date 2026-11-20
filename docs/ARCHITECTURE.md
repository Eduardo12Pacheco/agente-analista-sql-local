# Architecture

`local-sql-analyst-agent` is a local-first, hexagonal application in Python 3.12. The
domain is pure; the application layer orchestrates use cases through ports; adapters
provide the CLI, web UI, LLM backends, warehouse and repositories. Dependency direction
is enforced by import-linter contracts in `pyproject.toml` and by
`tests/architecture/test_import_contracts.py`.

> This is the T1 shell. The full architecture document (module tree, ports, patterns,
> defence in depth, extension guide) is completed in the release task.

## Layers

| Layer | Package | May import |
|---|---|---|
| Domain | `sqlagent.domain` | stdlib and `sqlglot` only |
| Application | `sqlagent.application` | `sqlagent.domain` only |
| Adapters | `sqlagent.adapters` | `sqlagent.domain`, `sqlagent.application` |
| Composition | `sqlagent.config`, `sqlagent.logging`, `sqlagent.bootstrap` | all layers (composition root) |

## System diagram

```mermaid
flowchart LR
  subgraph Adapters_in[Interfaces]
    CLI[CLI: ask / eval / serve / doctor / data]
    WEB[Web chat: FastAPI + HTMX + SSE]
  end
  subgraph App[Application]
    ASK[AskQuestion use case]
    EVAL[RunEvaluation use case]
    AG[AnalystAgent state machine]
    EV[Metrics / Gate / Summary]
  end
  subgraph Dom[Domain - pure]
    POL[SqlPolicy -> ValidatedQuery]
    SAN[DataSanitizer]
    RET[Bm25Retriever]
    CH[choose_chart]
    EQ[results_equivalent]
  end
  subgraph Adapters_out[Infrastructure adapters]
    LLM[(LLMPort: Ollama / Scripted / Replay / Recording)]
    WH[(WarehousePort: read-only locked DuckDB)]
    SEM[(Semantic layer YAML / manifest)]
    REP[(Report writer)]
  end
  CLI --> ASK
  CLI --> EVAL
  WEB --> ASK
  ASK --> AG
  EVAL --> AG
  EVAL --> EV
  AG --> POL
  AG --> SAN
  AG --> RET
  AG --> CH
  EV --> EQ
  AG --> LLM
  AG --> WH
  RET --> SEM
  EVAL --> REP
```

## Agent state machine

```mermaid
stateDiagram-v2
  [*] --> UNDERSTAND
  UNDERSTAND --> CLARIFY: empty / too long
  UNDERSTAND --> RETRIEVE
  RETRIEVE --> GENERATE
  GENERATE --> TOOL: action=lookup_values (<=3)
  TOOL --> GENERATE
  GENERATE --> VALIDATE: action=final_sql
  GENERATE --> CLARIFY: action=clarify
  GENERATE --> REFUSE: action=refuse
  GENERATE --> FAILED: protocol error after retry
  VALIDATE --> REFUSE: write/DDL/file intent
  VALIDATE --> REPAIR: other violation (<=2)
  VALIDATE --> EXECUTE
  EXECUTE --> REPAIR: SQL error (<=2)
  EXECUTE --> CHART
  REPAIR --> VALIDATE
  REPAIR --> FAILED: attempts exhausted
  CHART --> NARRATE
  NARRATE --> DONE
  CLARIFY --> DONE
  REFUSE --> DONE
  FAILED --> DONE
  DONE --> [*]
```

## Design patterns

To be documented with their concrete locations as the modules land: state machine
(handler table), chain of responsibility (SQL guard rules), parse-don't-validate
(`ValidatedQuery`), decorator (recording/replay LLMs), strategy (chart rules, LLM
backends), repository (semantic layer, benchmark), factory/composition root
(`bootstrap.py`), observer (`EventSink`), null object (`NullSink`) and record/replay
cassette testing.
