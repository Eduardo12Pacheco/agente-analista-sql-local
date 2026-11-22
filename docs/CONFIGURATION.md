# Configuración

Toda la configuración en tiempo de ejecución se lee de las variables de entorno `SQLAGENT_*`
(`pydantic-settings`, prefijo `SQLAGENT_`). Los archivos `.env` **no** se leen de forma
intencionada, para que un archivo suelto no pueda cambiar una ejecución determinista. Los ajustes
son inmutables en tiempo de ejecución; en las pruebas, pasa las anulaciones como variables de
entorno o como argumentos nombrados.

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `SQLAGENT_LLM_BACKEND` | `ollama` | Backend de completado: `ollama` o `replay` (cassette versionada, sin conexión). |
| `SQLAGENT_OLLAMA_URL` | `http://127.0.0.1:11434` | URL base de Ollama. Los hosts que no son loopback requieren `SQLAGENT_ALLOW_REMOTE_LLM=1`. |
| `SQLAGENT_MODEL` | `qwen2.5-coder:7b` | Nombre del modelo de Ollama usado para los completados (elegido en T12 por la EX del benchmark, D10). |
| `SQLAGENT_NUM_CTX` | `8192` | Ventana de contexto enviada como `options.num_ctx`. |
| `SQLAGENT_TEMPERATURE` | `0.0` | Temperatura de muestreo (valor por defecto determinista). |
| `SQLAGENT_SEED` | `42` | Semilla de muestreo enviada como `options.seed`. |
| `SQLAGENT_REQUEST_TIMEOUT_S` | `120` | Tiempo de espera de lectura para una solicitud a Ollama, en segundos. |
| `SQLAGENT_NUM_PREDICT` | `768` | Máximo de tokens generados por llamada. |
| `SQLAGENT_ALLOW_REMOTE_LLM` | `0` | Permite una URL de Ollama que no sea loopback; registra una advertencia cuando está activo (S19). |
| `SQLAGENT_MAX_ROWS` | `1000` | Tope estricto del resultado; un `LIMIT` de SQL mayor se recorta. |
| `SQLAGENT_UI_ROWS` | `200` | Filas renderizadas por la CLI y la interfaz web. |
| `SQLAGENT_QUERY_TIMEOUT_S` | `20` | Tiempo de espera del vigilante para una consulta de DuckDB. |
| `SQLAGENT_MEMORY_LIMIT` | `2GB` | `memory_limit` de DuckDB en la conexión de solo lectura. |
| `SQLAGENT_THREADS` | `4` | Hilos de trabajo de DuckDB. |
| `SQLAGENT_MAX_REPAIRS` | `2` | Máximo de llamadas REPAIR por pregunta. |
| `SQLAGENT_MAX_TOOL_CALLS` | `3` | Máximo de llamadas `lookup_values` por pregunta. |
| `SQLAGENT_DATA_DIR` | directorio de datos de usuario de la plataforma | Dónde vive el `warehouse-<sha8>.duckdb` materializado. |
| `SQLAGENT_WAREHOUSE_PATH` | sin definir | Usa un archivo DuckDB existente en lugar de materializar el paquete. |
| `SQLAGENT_LAKEHOUSE_MANIFEST` | sin definir | Ruta opcional del manifiesto de lakehouse (T11). |
| `SQLAGENT_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` o `CRITICAL`. |
| `SQLAGENT_LOG_FORMAT` | `console` | `console` para un renderizador de TTY, `json` para registros estructurados. |
| `SQLAGENT_UI_LANG` | `auto` | Idioma de la interfaz web: `auto`, `es` o `en`. |

## Ejemplos

```bash
# Native Ollama on the default port
SQLAGENT_MODEL=qwen2.5-coder:7b sqlagent ask "¿Cuántos procesos hay?"

# Ollama in Docker (scripts/ollama-docker.sh publishes 127.0.0.1:11435)
SQLAGENT_OLLAMA_URL=http://127.0.0.1:11435 sqlagent doctor

# Offline replay of a committed cassette (no model, no network)
SQLAGENT_LLM_BACKEND=replay sqlagent ask "¿Cuántos procesos hay?"
```

Los ajustes se validan al arrancar: un valor no válido (por ejemplo, un tiempo de espera negativo)
lanza un `ValidationError` de pydantic antes de cualquier acceso al almacén o a la red. Un campo
de configuración que falte en la tabla anterior hace fallar `tests/unit/test_settings.py`.
