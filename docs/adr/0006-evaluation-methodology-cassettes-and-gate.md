# ADR-0006: Metodología de evaluación, cassettes y puerta de regresión en CI

## Contexto

El repositorio debe demostrar la calidad de su agente con una medición reproducible, no con
ejemplos elegidos a mano. La medición debe ejecutarse sin conexión en CI, ser lo bastante estable
como para bloquear cada envío y, aun así, reflejar el comportamiento real del modelo cuando hay
un modelo de Ollama local disponible. Las opciones consideradas fueron un conjunto pequeño de
pruebas de humo (barato pero poco creíble), una puntuación LLM-as-a-judge (no determinista, cara y
difícil de usar como puerta) o la execution accuracy frente a un benchmark versionado con salidas
del modelo grabadas.

## Decisión

Usar la **execution accuracy (EX)** sobre el benchmark v1 de 72 elementos como métrica principal.
Una predicción es correcta cuando sus filas de resultado coinciden con el resultado del SQL de
referencia según D19 (ordenado solo cuando el SQL de referencia tiene un `ORDER BY` de primer
nivel; en otro caso, como multiconjunto, con la tolerancia documentada para flotantes). El motor
también informa intervalos de confianza de Wilson al 95 %, la tasa de SQL válido, la EX al primer
intento, la mejora por reparación, la precisión de rechazo, aclaración e inrespondibilidad, la
consistencia de pares ES↔EN, la exhaustividad de recuperación de tablas, la latencia y el uso de
tokens, y una taxonomía automática de fallos.

Cada ejecución escribe cuatro artefactos (`summary.json`, `results.jsonl`, `report.md`,
`report.html`); el informe HTML es autocontenido, con gráficos SVG en línea. La puerta de
regresión compara `overall.ex`, `overall.refusal_acc` y cada `by_category.*.ex` con una línea base
confirmada, y falla cuando una métrica baja más de `--max-drop` (por defecto 0).

Las salidas del modelo en vivo se graban como cassettes indexadas por el SHA-256 de la solicitud
canónica y se reproducen sin conexión. Las cassettes guardan solo un resumen, una vista previa de
200 caracteres del prompt y los metadatos de la respuesta, nunca el prompt completo. Una cassette
obsoleta es un fallo de primera clase (código de salida 4), y el prompt, la capa semántica y el
almacén se congelan después de la tarea de grabación (D18). El ejecutor de la evaluación acepta un
reloj inyectable para que las pruebas puedan demostrar resúmenes byte a byte idénticos para entradas
idénticas; la ruta de producción registra la latencia de reloj de pared.

## Consecuencias

* CI puede puntuar el benchmark completo sin conexión en bastante menos de un minuto y fallar ante
  una regresión sin GPU ni acceso a la red.
* Las cifras del README se generan a partir de `summary.json`, nunca se escriben a mano; la
  corrección del propio arnés se demuestra con un `OracleLLM` que obtiene 100 % y con un backend
  saboteado que debe activar la puerta.
* Las salidas grabadas son una única ejecución determinista en una sola máquina, no una afirmación
  sobre la precisión general de text-to-SQL; el benchmark es pequeño (n = 72) y los intervalos de
  confianza son amplios. Esta limitación está documentada en el README.
* Cualquier cambio en los prompts, la recuperación, el saneamiento o el almacén invalida las
  cassettes; la prueba de vigencia hace que esa rotura sea ruidosa en lugar de silenciosa.
* Las categorías no respondibles usan la precisión de expectativa en `by_category.*.ex`, para que la
  puerta pueda comparar cada categoría; la distinción está documentada en `docs/EVAL.md`.

## Alternativas consideradas

* **LLM-as-a-judge**: se rechaza porque un segundo modelo añade no determinismo, costo y una
  dependencia que contradice la restricción local-first y de cero claves.
* **Similitud de texto (BLEU/ROUGE) frente al SQL de referencia**: se rechaza porque se penalizarían
  formulaciones de SQL correctas distintas, y la métrica no es significativa para respuestas
  analíticas.
* **Un conjunto de pruebas de humo pequeño**: se rechaza porque no puede detectar regresiones a
  nivel de categoría ni sostener los desgloses publicados por categoría e idioma.
* **Ollama en vivo en cada envío a CI**: se rechaza porque CI no tiene GPU ni modelo, y el resultado
  sería lento, costoso y no determinista; grabar y reproducir ofrece la misma señal de regresión
  manteniendo reproducible la medición en vivo.
