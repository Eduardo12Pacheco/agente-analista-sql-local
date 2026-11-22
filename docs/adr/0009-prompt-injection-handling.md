# ADR-0009: Tratamiento de inyección de prompts en valores de datos no confiables

- **Estado:** Aceptada
- **Fecha:** 2026-11-20
- **Decisores:** Eduardo Pacheco

## Contexto

El almacén SERCOP contiene campos de texto libre (descripciones de licitaciones, nombres de
proveedores, descripciones de ítems) escritos por terceros. Cualquiera de ellos puede contener
instrucciones dirigidas al modelo: «ignora las instrucciones anteriores», un terminador de bloque
falso, texto bidireccional que oculta contenido o una carga XSS destinada a la interfaz web. El
agente reintroduce algunos de estos valores en los prompts para la narración y la búsqueda de
valores, así que el canal de datos y el canal de instrucciones deben separarse de forma deliberada.

La frontera de ejecución real es el validador de SQL (ADR-0003): los datos nunca deben poder
producir SQL nuevo. Pero el modelo aún puede confundirse hasta filtrar su prompt, narrar una
instrucción inyectada como un hecho o pedir llamadas adicionales a herramientas. La traza y la
interfaz deben hacer visibles los intentos de inyección sin destruir la evidencia.

## Decisión

Tratar cada valor de base de datos como texto hostil y enrutarlo a través de `DataSanitizer`:

1. Las instrucciones viven solo en el mensaje `system`; la pregunta del usuario es un mensaje
   `user`; el texto derivado de la base de datos aparece solo dentro de bloques de datos delimitados.
2. Los bloques son `<<DATA nonce=<8 hex> kind=<rows|lookup>>>`, una carga JSON y
   `<<END DATA nonce=<8 hex>>>`. El nonce es el SHA-256 de la carga, así que un atacante no puede
   incrustar previamente un terminador válido; cualquier `<<END DATA` o `<<DATA` dentro de una celda
   se neutraliza. El renderizado es determinista, lo que mantiene reproducibles las cassettes.
3. Eliminar los controles C0/C1 (salvo salto de línea y tabulador), las anulaciones bidireccionales,
   los caracteres de ancho cero y el BOM.
4. Truncar las celdas a 200 caracteres (incluido el marcador de advertencia) y las cargas a 20 filas
   para la narración y a 10 valores para las búsquedas.
5. Marcar, sin borrar, las celdas que coincidan con los patrones de inyección ES/EN, añadiendo
   `⟦flagged⟧` y contando la coincidencia. El conteo se expone en la traza del agente y la interfaz
   muestra una insignia; borrar el texto ocultaría el intento y cambiaría lo que ve el modelo de
   maneras más difíciles de explicar.
6. El agente nunca ejecuta texto derivado de los datos: el SQL solo proviene de las acciones
   `final_sql` o de reparación, y siempre pasa por `SqlPolicy` antes de ejecutarse.
7. La interfaz web aplica autoescape a cada valor (CSP `default-src 'self'`); las cargas XSS se
   muestran como texto, nunca se ejecutan.

## Consecuencias

- Una fila envenenada puede, en el peor caso, influir en la redacción de la respuesta, y el intento
  queda visible en la traza; no puede cambiar la forma del SQL, provocar llamadas adicionales a
  herramientas más allá de los límites estrictos ni alterar el esquema de salida.
- El renderizado determinista mantiene significativa la puerta de regresión sobre las salidas
  grabadas: las mismas filas del almacén producen los mismos bytes de prompt.
- El truncado y los topes de filas acotan el tamaño y el costo del prompt, a costa de que el modelo
  no vea todas las filas de un resultado grande. La narración es un resumen, no un informe
  exhaustivo.
- La marcación por patrones es heurística y deliberadamente conservadora; son posibles falsos
  positivos (el marcador es visible y el texto original se conserva). El validador, no el marcador,
  sigue siendo la frontera de seguridad.
- El nonce es un hash de contenido, no un secreto. Evita la falsificación de delimitadores, no los
  ataques de colisión deliberados, que son irrelevantes para esta herramienta local.

## Alternativas consideradas

- **Confiar en que el modelo ignore las instrucciones de los datos:** rechazada; es exactamente el
  ataque que la funcionalidad debe soportar.
- **Escapar o eliminar toda la puntuación o las palabras con apariencia de instrucción:** rechazada
  porque destruye texto español legítimo y oculta los ataques en lugar de mostrarlos.
- **Una llamada separada al LLM para clasificar cada valor:** rechazada por lenta, costosa y poco
  fiable en un modelo local de 7–8B; un sanitizador determinista es comprobable y auditable.
- **Escapar HTML dentro del sanitizador:** rechazada porque el sanitizador alimenta prompts, no HTML.
  La capa de plantillas se encarga del escape HTML y tiene su propia prueba de XSS.
