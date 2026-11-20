# ADR-0007: Web chat stack and vendored browser assets

- Status: Accepted
- Date: 2026-11-20
- Task: T10

## Context

The project needs a finished, local-first chat that streams the agent's phases and
shows the answer narrative, the validated SQL, the bounded result table, a chart and
the execution trace. Constraints that shaped the decision:

- Local-first: no CDN, no build step, no Node runtime for end users, no telemetry and
  no non-loopback destination except the configured Ollama URL.
- Python-only packaging: the wheel must contain every asset, because the UI is served
  by `uv tool install` on Linux, macOS and Windows.
- Security: a strict CSP without inline scripts, server-side rendering/escaping of
  untrusted database values, same-origin POST checks and no CORS.
- Testability: route tests with FastAPI's `TestClient` and a browser journey with
  Playwright, both without a model or network egress.
- Portfolio convention L5: default HTTP port in 17000–17999; the CLI's documented
  example uses `--port 8765`, but the default is `17080`.

## Decision

- **FastAPI + Jinja2 + HTMX 2.0.11 + htmx-ext-sse 2.2.4 + Chart.js 4.6.1**, with one
  small vanilla ES module (`static/chat.js`) for the composer, theme toggle, chart
  rendering and copy buttons. No framework, bundler or Node toolchain at runtime.
- **Vendored assets.** `scripts/vendor_assets.py` downloads each pinned npm tarball
  from the registry, verifies `dist.integrity` (SHA-512), extracts only the needed
  `dist/*.min.js`, copies the package licence, writes `VENDOR.json` and regenerates
  the vendored section of `THIRD_PARTY_NOTICES.md`. Assets are committed so the wheel
  works offline; `--check` proves they are reproducible.
- **SSE without an extra dependency.** `POST /ask` starts a daemon thread running the
  agent with a thread-safe `queue.Queue` event sink and returns an HTML fragment with
  `sse-connect`. `GET /ask/stream/{id}` drains the queue and emits `phase`,
  `retrieval`, `sql`, `result`, `chart`, `answer`, `error` and a final `done` frame;
  `sse-close="done"` stops the browser's EventSource. The same thread-safe queue keeps
  the producer independent of uvicorn's event loop, which also makes the route tests
  deterministic.
- **Server-side rendering.** The answer card, result table, SQL highlighting (sqlglot
  tokenizer) and schema drawer are rendered by Jinja templates. Only the chart is
  rendered in the browser from a JSON payload embedded in a data attribute. Jinja
  autoescape plus explicit escaping in the highlighter keep untrusted values inert.
- **Security headers in middleware:** CSP `default-src 'self'`, `nosniff`,
  `no-referrer`, `X-Frame-Options: DENY`; foreign `Origin` on `/ask` and `/api/ask`
  returns 403. Static assets and SSE stay same-origin.
- **No-JS baseline.** The composer posts to `/api/ask`; when the request accepts HTML
  it returns the full server-rendered page with the answer instead of JSON, while
  API clients continue to receive `AgentAnswer` JSON (`answer_id` included for CSV).

## Consequences

- The wheel grows by roughly 270 KB of minified JS and carries a verified licence
  bundle; there is no CDN request and the e2e test asserts all requests stay on
  loopback.
- A thread per in-flight chat request is acceptable for a single-user local app. The
  run/answer store is bounded (LRU 100, TTL 30 min); the DuckDB adapter serialises
  queries behind its own lock.
- Rendering fragments twice (streaming slots + final answer body) is a deliberate
  trade-off: no client-side templating, no full-page reloads, and the final answer is
  accessible immediately.
- HTMX/Chart.js versions are pinned in `VENDOR.json`; upgrading requires rerunning
  the vendor script and the browser journey.
- The default port is `17080` to respect the portfolio port range; the plan's
  `--port 8765` example remains a valid explicit override.

## Alternatives considered

- **React/Vue SPA with a bundler.** Rejected: adds Node, a build pipeline and
  hundreds of transitive packages for one page, against the local-first, minimal
  dependency constraints.
- **Server-sent events via `sse-starlette`.** Rejected: D2 deliberately avoids the
  dependency; Starlette's `StreamingResponse` plus a queue is enough.
- **WebSockets.** Rejected: the flow is one-way after submission and SSE survives
  proxies/reconnects with less code.
- **Client-side Markdown/SQL highlighting.** Rejected: another dependency and an XSS
  surface; sqlglot is already present server-side.
- **CDN-hosted HTMX/Chart.js.** Rejected: violates offline-first, CSP and the
  no-network-in-tests rule.
- **Serving the assets from a second process or a docs site.** Rejected: the CLI must
  install and run as a single local process.
