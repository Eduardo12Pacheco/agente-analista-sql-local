# Contribuir

Gracias por tu interés en `local-sql-analyst-agent`. Este documento describe el flujo de trabajo
local y las puertas de calidad que debe superar cualquier cambio.

## Configuración

Requisitos previos: Python 3.12 y [uv](https://docs.astral.sh/uv/) (no se necesitan Docker ni Ollama
para la suite de pruebas por defecto).

```bash
uv sync
uv run pytest -m "not e2e"
```

## Comandos

| Comando | Propósito |
|---|---|
| `make install` | Sincroniza el entorno a partir de `uv.lock`. |
| `make lint` | `ruff check` más `ruff format --check`. |
| `make types` | `mypy --strict src`. |
| `make test` | Pruebas unitarias, de integración, de contrato y de arquitectura. |
| `make e2e` | Pruebas end-to-end con Playwright (requiere `uv run playwright install chromium`). |
| `make eval-replay` | Reproduce contra el benchmark las salidas grabadas confirmadas. |
| `make smoke` | Construye el wheel y ejecuta la prueba de humo del instalador sin conexión. |
| `make changelog` | Previsualiza las notas de la versión para la última etiqueta. |
| `make build` | Construye el wheel y el sdist. |

La puerta local completa es:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy --strict src \
  && uv run lint-imports && uv lock --check && uv run pytest -m "not e2e"
```

## Estilo

- Python 3.12, diseño `src/`, totalmente tipado (`mypy --strict`).
- Arquitectura hexagonal: `domain` es puro, `application` depende de `domain`, y `adapters` puede
  depender de ambos. `tests/architecture` lo impone con import-linter.
- Las pruebas se escriben primero: escribe la prueba que falla, implementa y luego refactoriza.
  Nunca debilites, omitas ni borres una prueba para que la suite pase.
- Sin red en las pruebas; el fixture autouse de `tests/conftest.py` bloquea los sockets que no son
  de loopback.

## Commits

Usa Conventional Commits en inglés (`feat(guardrails): ...`, `test(eval): ...`, `docs: ...`,
`ci: ...`, `chore: ...`). Mantén cada commit enfocado y por debajo de unas 400 líneas cambiadas. No
añadas trailers de atribución de IA.

## Congelación del prompt y re-grabación

Las salidas grabadas del LLM (cassettes) se indexan por un digest de la solicitud exacta. Cualquier
cambio en los prompts, los few-shots, la capa semántica, los parámetros de recuperación, el
renderizado del sanitizador o los Parquet del almacén las invalida. La prueba de integración
`tests/integration/test_recordings_fresh.py` falla con `CassetteMiss`; vuelve a grabar con el helper
de Ollama en Docker y `sqlagent eval --llm ollama --record`, y después confirma las nuevas cassettes,
`eval/baseline.json` y `eval/reports/latest/` en el mismo cambio. No actualices la línea base para
ocultar una regresión: la puerta de reproducción de CI compara contra ella.

## CI

GitHub Actions se ejecuta en cada envío a `main` y en cada pull request:

| Job | Qué demuestra |
|---|---|
| `lint` | `ruff check`, `ruff format --check`, `mypy --strict src`, `lint-imports` y el lockfile. |
| `test` | Suite unitaria, de integración, de contrato y de arquitectura en Ubuntu, Windows y macOS (3.12), más Ubuntu 3.13; cobertura ≥ 85 % en Ubuntu 3.12. |
| `e2e` | Recorrido del chat con Playwright, instalado con Chromium en Ubuntu. |
| `eval-gate` | Reproduce las cassettes confirmadas y falla cuando EX, la precisión de rechazo o cualquier categoría retroceden frente a `eval/baseline.json`. |
| `installer-smoke` | Construye el wheel, lo instala con `uv tool install` y ejecuta el script de consola sin conexión en los tres sistemas operativos. |
| `security` | gitleaks sobre todo el historial y `pip-audit` sobre las dependencias bloqueadas. |

Ejecuta los mismos jobs localmente con `make check`, `make e2e`, `make eval-replay` y `make smoke`.
La prueba de humo nunca necesita Ollama ni una conexión de red.

## Releases

Las versiones se publican mediante etiquetas anotadas:

1. Define la misma versión en `pyproject.toml` y en `sqlagent.__version__` (la versión se lee de
   los metadatos instalados, así que no hace falta una constante duplicada).
2. Actualiza `CHANGELOG.md` y etiqueta `v<version>`.
3. Al subir la etiqueta se ejecuta `.github/workflows/release.yml`: construye el wheel y el sdist,
   escribe `SHA256SUMS`, ejecuta la matriz de humo del instalador en Ubuntu, Windows y macOS, genera
   las notas a partir de Conventional Commits con git-cliff y publica la Release de GitHub con los
   distribuibles, las sumas de verificación, `report.md` y `summary.json`.

Previsualiza las notas localmente con `make changelog` (usa `uvx git-cliff`). Nunca reescribas ni
fuerces el envío de etiquetas que ya se hayan publicado.

## Reportar problemas de seguridad

Consulta [SECURITY.md](SECURITY.md). Por favor, no abras issues públicos para vulnerabilidades.
