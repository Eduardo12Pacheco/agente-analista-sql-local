# Política de seguridad

## Versiones compatibles

| Versión | Compatible |
|---|---|
| `0.1.x` (desarrollo) | Sí |

## Reportar una vulnerabilidad

Usa el reporte privado de vulnerabilidades de GitHub en este repositorio (Security → Advisories →
Report a vulnerability). No abras un issue público para problemas de seguridad. Incluye una
reproducción mínima, la versión afectada y el impacto. Nuestro objetivo es confirmar la recepción de
los reportes en pocos días.

## Diseño de seguridad

El agente solo puede ejecutar sentencias `SELECT` analíticas únicas y de solo lectura. La defensa en
profundidad se aplica en cuatro niveles:

1. Reglas del prompt que marcan los valores de la base de datos como datos no confiables.
2. Una lista blanca de AST de `sqlglot` (`SqlPolicy`) que rechaza escrituras, DDL, acceso a archivos
   y tablas desconocidas.
3. Una conexión de DuckDB abierta con `read_only=True`, con el acceso externo deshabilitado y la
   configuración bloqueada.
4. Límites de recursos: tope de filas, tiempo de espera de consultas, límite de memoria y bucles
   acotados del agente.

El único destino de red es la URL configurada de Ollama, que por defecto es loopback. No se requieren
claves de API ni servicios en la nube.
