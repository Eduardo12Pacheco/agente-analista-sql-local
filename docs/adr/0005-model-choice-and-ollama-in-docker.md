# ADR-0005: Elección del modelo y evaluación de Ollama en Docker

Estado: aceptada (2026-11-20)

## Contexto

El agente necesita un modelo local que siga instrucciones y produzca SQL restringido por JSON
de forma fiable en español e inglés, que quepa en una RTX 4060 de 8 GB y que funcione sin
ninguna API en la nube. Dos candidatos con licencia Apache-2.0 caben en el presupuesto de memoria
con `num_ctx=8192`: `qwen3:8b` (5,2 GB, razonamiento conmutable, narración multilingüe sólida) y
`qwen2.5-coder:7b` (4,7 GB, especializado en código, con una precisión de ejecución zero-shot
reportada de alrededor del 42,6 % en BIRD-dev). El plan fija la regla de selección: medir ambos
en el benchmark v1 con configuraciones deterministas idénticas y quedarse con la mayor execution
accuracy global; en caso de empate, gana `qwen3:8b`.

El host no tiene Ollama instalado de forma nativa y no se debe asumir capacidad compartida de GPU.
Por eso la evaluación debe ejecutar la imagen oficial de Ollama en Docker, con un volumen con
nombre que pertenezca a este repositorio, un puerto de host no predeterminado y la misma
configuración que registra la cassette incluida.

## Decisión

- **Modelos.** Evaluar `qwen3:8b` y `qwen2.5-coder:7b` con `temperature=0`, `seed=42`,
  `num_ctx=8192`, `num_predict=768` y la narración desactivada. Para qwen3 se envía
  `think:false`.
- **Por defecto.** Fijar `DEFAULT_MODEL` a partir del resultado medido. La ejecución del 2026-11-20
  produjo EX 63,3 % [50,7 %, 74,4 %] para `qwen2.5-coder:7b` y 61,7 % [49,0 %, 72,9 %] para
  `qwen3:8b`, así que `qwen2.5-coder:7b` es el valor por defecto. Los intervalos se solapan; el
  README y `docs/EVAL.md` indican que se trata de una diferencia pequeña y ruidosa sobre 60
  elementos respondibles.
- **Ejecución.** `scripts/ollama-docker.sh|ps1` gestionan el contenedor `ollama-sqlagent` a partir
  de la imagen `ollama/ollama:0.40.16`, el volumen `ollama-portfolio`, el puerto de host
  `127.0.0.1:11435` y `--gpus all` cuando el runtime de NVIDIA está disponible. Ollama nativo en el
  puerto por defecto `127.0.0.1:11434` sigue siendo compatible para los usuarios finales.
- **Reproducibilidad.** Solo la cassette del modelo por defecto se incluye en el wheel
  (`resources/recordings/<slug>/p1.jsonl`). La cassette del otro modelo se conserva en
  `eval/recordings-extra/` para la reproducibilidad, fuera del wheel. Las ejecuciones reales usan
  `--record`; los informes confirmados, la línea base y la prueba de vigencia se reproducen sin
  conexión.
- **Ablaciones.** El modelo por defecto también se mide con `--max-repairs 0` y `--no-retrieval`.
  Sus informes se confirman en el repositorio, pero no se graban en cassette.
- **GPU compartida.** Cualquier comando que use la GPU se ejecuta bajo
  `flock /tmp/portfolio-gpu.lock`, para que los agentes paralelos del portafolio no compitan por la
  tarjeta. El contenedor y el volumen nunca se comparten con otros repositorios.

## Consecuencias

- El proyecto funciona por completo sin conexión mediante la cassette confirmada; la inferencia en
  vivo requiere Docker (o Ollama nativo) y una descarga de modelo de 5 GB.
- El modelo por defecto es una elección medida, no una preferencia, y puede revisarse repitiendo la
  evaluación documentada; cambiarlo invalida la cassette y exige volver a grabarla según la regla
  de congelación del prompt.
- Incluir una sola cassette mantiene el wheel por debajo de su presupuesto de tamaño, mientras la
  segunda ejecución sigue siendo auditable en el repositorio.
- Docker es una dependencia de desarrollo y de evaluación, no un requisito previo de instalación
  para el paquete `uv tool install`.

## Alternativas consideradas

- **Un solo modelo.** Rechazada: el plan exige una comparación medida y una regla de selección
  documentada.
- **APIs de LLM en la nube.** Rechazadas por la restricción de cero claves y sin API de pago.
- **Ollama nativo en el host.** Rechazado para la evaluación porque el host no lo tiene y el
  contenedor ofrece una imagen fijada y reproducible.
- **Elegir el modelo más grande por su reputación.** Rechazada: el benchmark v1 es la fuente de
  verdad, y el modelo de código más pequeño ganó sobre este almacén.
- **Incluir ambas cassettes en el wheel.** Rechazada: tamaño innecesario, y la ruta de replay solo
  necesita el modelo por defecto.
