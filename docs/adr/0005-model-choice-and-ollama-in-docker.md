# ADR-0005: Model choice and Ollama-in-Docker evaluation

Status: accepted (2026-11-20)

## Context

The agent needs a local instruction-following model that produces JSON-constrained
SQL reliably in Spanish and English, fits an 8 GB RTX 4060 and runs without any
cloud API. Two Apache-2.0 candidates fit the memory budget at `num_ctx=8192`:
`qwen3:8b` (5.2 GB, thinking switchable, strong multilingual narration) and
`qwen2.5-coder:7b` (4.7 GB, code-specialised, reported around 42.6% zero-shot
BIRD-dev execution accuracy). The plan fixes the selection rule: measure both on
benchmark v1 with identical deterministic settings and take the higher overall
execution accuracy; a tie goes to `qwen3:8b`.

The host does not have Ollama installed natively and shared GPU capacity must not
be assumed. Evaluation therefore has to run the official Ollama image in Docker,
with a named volume that belongs to this repository, a non-default host port and
the same configuration the shipped cassette records.

## Decision

- **Models.** Evaluate `qwen3:8b` and `qwen2.5-coder:7b` with `temperature=0`,
  `seed=42`, `num_ctx=8192`, `num_predict=768` and narration disabled. For qwen3
  send `think:false`.
- **Default.** Set `DEFAULT_MODEL` from the measured result. The 2026-11-20 run
  produced EX 63.3% [50.7%, 74.4%] for `qwen2.5-coder:7b` and 61.7%
  [49.0%, 72.9%] for `qwen3:8b`, so `qwen2.5-coder:7b` is the default. The
  intervals overlap; the README and `docs/EVAL.md` state that this is a small,
  noisy difference on 60 answerable items.
- **Runtime.** `scripts/ollama-docker.sh|ps1` manage container `ollama-sqlagent`
  from image `ollama/ollama:0.40.16`, volume `ollama-portfolio`, host port
  `127.0.0.1:11435` and `--gpus all` when the NVIDIA runtime is available.
  Native Ollama on the default `127.0.0.1:11434` remains supported for end users.
- **Reproducibility.** Only the default model's cassette ships in the wheel
  (`resources/recordings/<slug>/p1.jsonl`). The other model's cassette is kept in
  `eval/recordings-extra/` for reproducibility, outside the wheel. Real runs use
  `--record`; the committed reports, baseline and freshness test replay offline.
- **Ablations.** The default model is also measured with `--max-repairs 0` and
  `--no-retrieval`. Their reports are committed but not recorded to cassette.
- **Shared GPU.** Any command that uses the GPU runs under
  `flock /tmp/portfolio-gpu.lock` so parallel portfolio agents do not contend for
  the card. The container and volume are never shared with other repositories.

## Consequences

- The project works fully offline through the committed cassette; live inference
  requires Docker (or a native Ollama) and a 5 GB model download.
- The default model is a measured choice, not a preference, and can be revisited
  by re-running the documented evaluation; changing it invalidates the cassette
  and requires re-recording under the prompt-freeze rule.
- Shipping only one cassette keeps the wheel below its size budget while the
  second run remains auditable in the repository.
- Docker is a development/evaluation dependency, not an install prerequisite for
  the `uv tool install` package.

## Alternatives considered

- **One model only.** Rejected: the plan requires a measured comparison and a
  documented selection rule.
- **Cloud LLM APIs.** Rejected by the zero-keys, no-paid-API constraint.
- **Native Ollama on the host.** Rejected for evaluation because the host does
  not have it and the container gives a pinned, reproducible image.
- **Picking the bigger model by reputation.** Rejected: benchmark v1 is the
  source of truth, and the smaller coder model won on this warehouse.
- **Committing both cassettes in the wheel.** Rejected: unnecessary size, and the
  replay path only ever needs the default model.
