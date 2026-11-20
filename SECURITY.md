# Security policy

## Supported versions

| Version | Supported |
|---|---|
| `0.1.x` (development) | Yes |

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting on this repository
(Security → Advisories → Report a vulnerability). Do not open a public issue for
security problems. Include a minimal reproduction, the affected version and the
impact. We aim to acknowledge reports within a few days.

## Security design

The agent can only execute single read-only analytical `SELECT` statements. Defence in
depth applies at four levels:

1. Prompt rules that mark database values as untrusted data.
2. A `sqlglot` AST allowlist (`SqlPolicy`) that rejects writes, DDL, file access and
   unknown tables.
3. A DuckDB connection opened `read_only=True` with external access disabled and
   configuration locked.
4. Resource limits: row cap, query timeout, memory limit and bounded agent loops.

The only network destination is the configured Ollama URL, which defaults to loopback.
No API keys or cloud services are required.
