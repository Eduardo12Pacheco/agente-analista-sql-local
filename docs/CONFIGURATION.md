# Configuration

All runtime configuration is read from `SQLAGENT_*` environment variables
(`pydantic-settings`, prefix `SQLAGENT_`). `.env` files are intentionally **not**
read, so a stray file cannot change a deterministic run. Settings are immutable at
runtime; pass overrides as environment variables or keywords in tests.

| Variable | Default | Description |
|---|---|---|
| `SQLAGENT_LLM_BACKEND` | `ollama` | Completion backend: `ollama` or `replay` (committed cassette, offline). |
| `SQLAGENT_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama base URL. Non-loopback hosts require `SQLAGENT_ALLOW_REMOTE_LLM=1`. |
| `SQLAGENT_MODEL` | `qwen3:8b` | Ollama model name used for completions (provisional until T12). |
| `SQLAGENT_NUM_CTX` | `8192` | Context window sent as `options.num_ctx`. |
| `SQLAGENT_TEMPERATURE` | `0.0` | Sampling temperature (deterministic default). |
| `SQLAGENT_SEED` | `42` | Sampling seed sent as `options.seed`. |
| `SQLAGENT_REQUEST_TIMEOUT_S` | `120` | Read timeout for one Ollama request, in seconds. |
| `SQLAGENT_NUM_PREDICT` | `768` | Maximum generated tokens per call. |
| `SQLAGENT_ALLOW_REMOTE_LLM` | `0` | Allow a non-loopback Ollama URL; logs a warning when enabled (S19). |
| `SQLAGENT_MAX_ROWS` | `1000` | Hard result cap; a larger SQL `LIMIT` is clamped. |
| `SQLAGENT_UI_ROWS` | `200` | Rows rendered by the CLI/web UI. |
| `SQLAGENT_QUERY_TIMEOUT_S` | `20` | Watchdog timeout for one DuckDB query. |
| `SQLAGENT_MEMORY_LIMIT` | `2GB` | DuckDB `memory_limit` on the read-only connection. |
| `SQLAGENT_THREADS` | `4` | DuckDB worker threads. |
| `SQLAGENT_MAX_REPAIRS` | `2` | Maximum REPAIR calls per question. |
| `SQLAGENT_MAX_TOOL_CALLS` | `3` | Maximum `lookup_values` tool calls per question. |
| `SQLAGENT_DATA_DIR` | platform user data dir | Where the materialised `warehouse-<sha8>.duckdb` lives. |
| `SQLAGENT_WAREHOUSE_PATH` | unset | Use an existing DuckDB file instead of materialising the bundle. |
| `SQLAGENT_LAKEHOUSE_MANIFEST` | unset | Optional lakehouse manifest path (T11). |
| `SQLAGENT_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. |
| `SQLAGENT_LOG_FORMAT` | `console` | `console` for a TTY renderer, `json` for structured logs. |
| `SQLAGENT_UI_LANG` | `auto` | Web UI chrome language: `auto`, `es` or `en`. |

## Examples

```bash
# Native Ollama on the default port
SQLAGENT_MODEL=qwen2.5-coder:7b sqlagent ask "¿Cuántos procesos hay?"

# Ollama in Docker (scripts/ollama-docker.sh publishes 127.0.0.1:11435)
SQLAGENT_OLLAMA_URL=http://127.0.0.1:11435 sqlagent doctor

# Offline replay of a committed cassette (no model, no network)
SQLAGENT_LLM_BACKEND=replay sqlagent ask "¿Cuántos procesos hay?"
```

Settings are validated at startup: an invalid value (for example a negative
timeout) raises a pydantic `ValidationError` before any warehouse or network
access. A settings field missing from the table above fails
`tests/unit/test_settings.py`.
