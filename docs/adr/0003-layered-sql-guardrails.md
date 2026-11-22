# ADR-0003: Guardarraíles SQL por capas con una lista blanca de AST

- **Estado:** Aceptada
- **Fecha:** 2026-11-20
- **Decisores:** Eduardo Pacheco

## Contexto

El agente convierte preguntas en lenguaje natural en SQL y ejecuta el resultado contra un
almacén DuckDB local. Los modelos locales cometen errores, y los datos con inyección de prompts
pueden intentar llevar al modelo hacia escrituras, acceso a archivos o agotamiento de recursos.
El almacén es de solo lectura, pero un único `read_csv('/etc/passwd')`, un `COPY ... TO`, un
`ATTACH` o un producto cartesiano patológico seguirían siendo inaceptables en una herramienta de
escritorio que se presenta como segura.

Los filtros a nivel de texto y las instrucciones del prompt no son una frontera de ejecución: el
modelo puede equivocarse o ser manipulado, y la conexión no debe depender de la buena voluntad
del modelo.

## Decisión

Usar **defensa en profundidad** con cuatro capas independientes:

1. **Reglas del prompt** explican el dialecto de DuckDB, el alcance de solo lectura y el
   protocolo JSON. Mejoran las probabilidades del modelo, pero nunca se confía en ellas.
2. **`SqlPolicy`** analiza cada sentencia con sqlglot (dialecto `duckdb`) y aplica una cadena
   ordenada de responsabilidad: longitud, análisis de una sola sentencia, raíz solo SELECT, lista
   blanca de nodos, lista blanca de funciones, lista blanca de tablas del catálogo o de CTE,
   límites de complejidad y una reescritura de `LIMIT` a nivel de AST. Los nodos, funciones o
   tablas desconocidos se rechazan; el SQL que se ejecuta se regenera a partir del AST validado
   (sin comentarios), de modo que las peculiaridades del analizador no puedan introducir una
   segunda interpretación.
3. **`ValidatedQuery`** es un tipo inmutable que solo puede construir `SqlPolicy.validate`. El
   puerto del almacén acepta ese tipo, de modo que «este SQL pasó el guardarraíl» sea una
   propiedad a nivel de tipos (analizar, no validar: *parse, don't validate*).
4. **Una conexión de DuckDB bloqueada y de solo lectura** (`read_only=True`, acceso externo
   deshabilitado, carga automática de extensiones desactivada, límites de memoria e hilos), además
   de un tiempo de espera de vigilancia y un tope de filas.

Los rechazos llevan un `GuardrailCode` estable. Los códigos de escritura, DDL o intención de
acceso a archivos se rechazan sin reparación; las violaciones reparables (por ejemplo, una
columna desconocida) pueden devolverse al modelo con el texto del error. Los corpus de SQL
adversarial y legítimo, la propiedad de fuzzing y la prueba de comportamiento fijado de sqlglot
mantienen honesta la política a través de las actualizaciones.

## Consecuencias

- Un valor de datos envenenado no puede provocar la ejecución de algo que no sea SELECT ni el
  acceso a archivos, incluso cuando un modelo «obediente» simulado sigue la inyección; la política
  de AST es la frontera real.
- La política es determinista y rápida (p95 inferior a 20 ms en el corpus analítico), así que puede
  ejecutarse en cada intento sin un costo de latencia medible.
- La lista blanca es deliberadamente conservadora: una nueva función analítica o construcción SQL
  debe añadirse con una prueba y una decisión, en lugar de aceptarse de forma implícita.
- Las actualizaciones mayores de sqlglot pueden cambiar las formas del AST; una prueba de
  comportamiento fijado falla de forma ruidosa y exige una revisión explícita, en lugar de ampliar
  o romper la política en silencio.
- Algunas funciones legítimas de DuckDB (funciones de tabla, `PIVOT`, `UNNEST` fuera de CTE,
  muestreo, lecturas con bloqueo) no están disponibles para el agente. No se necesitan para el
  benchmark y la restricción está documentada.

## Alternativas consideradas

- **Seguridad solo mediante el prompt:** rechazada; las instrucciones no son una frontera de
  ejecución.
- **Listas negras con expresiones regulares o palabras clave:** rechazadas porque SQL depende del
  contexto y las listas de palabras clave se eluden con facilidad mediante comentarios,
  mayúsculas o sintaxis alternativa.
- **Ejecutar SQL arbitrario y confiar en la conexión de solo lectura:** rechazada porque la
  solo lectura no impide leer archivos, instalar extensiones, producir productos cartesianos
  enormes ni consultar el esquema de información.
- **Un analizador o proxy SQL separado:** rechazado como dependencia innecesaria; sqlglot ya es
  necesario para la regeneración consciente del dialecto y para la extracción de tablas del
  benchmark.
