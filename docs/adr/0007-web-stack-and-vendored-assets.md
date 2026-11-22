# ADR-0007: Pila del chat web y activos del navegador incluidos

- Estado: Aceptada
- Fecha: 2026-11-20
- Tarea: T10

## Contexto

El proyecto necesita un chat terminado y local-first que transmita las fases del agente y muestre
la narrativa de la respuesta, el SQL validado, la tabla de resultados acotada, un gráfico y la
traza de ejecución. Restricciones que dieron forma a la decisión:

- Local-first: sin CDN, sin paso de compilación, sin runtime de Node para los usuarios finales, sin
  telemetría y sin destinos fuera de loopback, salvo la URL configurada de Ollama.
- Empaquetado solo en Python: el wheel debe contener todos los activos, porque la interfaz se sirve
  con `uv tool install` en Linux, macOS y Windows.
- Seguridad: una CSP estricta sin scripts en línea, renderizado y escape del lado del servidor de
  valores de base de datos no confiables, comprobaciones de POST del mismo origen y sin CORS.
- Comprobabilidad: pruebas de rutas con `TestClient` de FastAPI y un recorrido por el navegador con
  Playwright, ambos sin modelo ni salida a la red.
- Convención de portafolio L5: puerto HTTP por defecto en el rango 17000–17999; el ejemplo
  documentado de la CLI usa `--port 8765`, pero el valor por defecto es `17080`.

## Decisión

- **FastAPI + Jinja2 + HTMX 2.0.11 + htmx-ext-sse 2.2.4 + Chart.js 4.6.1**, con un módulo ES vanilla
  pequeño (`static/chat.js`) para el compositor, el cambio de tema, el dibujo de gráficos y los
  botones de copia. Sin framework, empaquetador ni cadena de herramientas de Node en tiempo de
  ejecución.
- **Activos incluidos.** `scripts/vendor_assets.py` descarga cada tarball npm fijado desde el
  registro, verifica `dist.integrity` (SHA-512), extrae solo los `dist/*.min.js` necesarios, copia
  la licencia del paquete, escribe `VENDOR.json` y regenera la sección incluida de
  `THIRD_PARTY_NOTICES.md`. Los activos se confirman para que el wheel funcione sin conexión;
  `--check` demuestra que son reproducibles.
- **SSE sin dependencia adicional.** `POST /ask` inicia un hilo demonio que ejecuta el agente con un
  receptor de eventos `queue.Queue` seguro para hilos y devuelve un fragmento HTML con
  `sse-connect`. `GET /ask/stream/{id}` vacía la cola y emite los marcos `phase`, `retrieval`, `sql`,
  `result`, `chart`, `answer`, `error` y un marco final `done`; `sse-close="done"` detiene el
  EventSource del navegador. La misma cola segura para hilos mantiene al productor independiente del
  bucle de eventos de uvicorn, lo que además hace deterministas las pruebas de rutas.
- **Renderizado en el servidor.** La tarjeta de respuesta, la tabla de resultados, el resaltado de
  SQL (tokenizador de sqlglot) y el cajón del esquema los renderizan plantillas Jinja. Solo el
  gráfico se renderiza en el navegador, a partir de una carga JSON incrustada en un atributo de
  datos. El autoescape de Jinja, junto con el escape explícito en el resaltador, mantiene inertes los
  valores no confiables.
- **Cabeceras de seguridad en el middleware:** CSP `default-src 'self'`, `nosniff`, `no-referrer`,
  `X-Frame-Options: DENY`; un `Origin` ajeno en `/ask` y `/api/ask` devuelve 403. Los activos
  estáticos y SSE permanecen en el mismo origen.
- **Línea base sin JavaScript.** El compositor envía a `/api/ask`; cuando la solicitud acepta HTML,
  devuelve la página completa renderizada en el servidor con la respuesta en lugar de JSON, mientras
  que los clientes de API siguen recibiendo el JSON de `AgentAnswer` (`answer_id` incluido para el
  CSV).

## Consecuencias

- El wheel crece unos 270 KB de JS minificado y lleva un paquete de licencias verificado; no hay
  solicitudes a CDN, y la prueba e2e afirma que todas las solicitudes permanecen en loopback.
- Un hilo por solicitud de chat en curso es aceptable para una aplicación local de un solo usuario.
  El almacén de ejecuciones y respuestas está acotado (LRU de 100, TTL de 30 min); el adaptador de
  DuckDB serializa las consultas detrás de su propio bloqueo.
- Renderizar los fragmentos dos veces (ranuras de streaming + cuerpo de la respuesta final) es un
  compromiso deliberado: sin plantillas en el cliente, sin recargas de página completa, y la
  respuesta final es accesible de inmediato.
- Las versiones de HTMX y Chart.js están fijadas en `VENDOR.json`; actualizarlas exige volver a
  ejecutar el script de activos y el recorrido por el navegador.
- El puerto por defecto es `17080` para respetar el rango de puertos del portafolio; el ejemplo
  `--port 8765` del plan sigue siendo una anulación explícita válida.

## Alternativas consideradas

- **SPA con React/Vue y un empaquetador.** Rechazada: añade Node, un pipeline de compilación y
  cientos de paquetes transitivos para una sola página, contra las restricciones local-first y de
  dependencias mínimas.
- **Server-sent events mediante `sse-starlette`.** Rechazada: D2 evita deliberadamente la
  dependencia; `StreamingResponse` de Starlette más una cola basta.
- **WebSockets.** Rechazada: el flujo es unidireccional tras el envío, y SSE sobrevive a los
  proxies y a las reconexiones con menos código.
- **Resaltado de Markdown/SQL en el cliente.** Rechazada: otra dependencia y una superficie de XSS;
  sqlglot ya está presente en el servidor.
- **HTMX/Chart.js alojados en CDN.** Rechazada: viola la norma de funcionamiento sin conexión, la
  CSP y la regla de no usar red en las pruebas.
- **Servir los activos desde un segundo proceso o desde un sitio de documentación.** Rechazada: la
  CLI debe instalarse y ejecutarse como un único proceso local.
