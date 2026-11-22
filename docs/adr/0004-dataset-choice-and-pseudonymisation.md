# ADR-0004: Conjunto de datos SERCOP OCDS 2021, licencia y pseudonimización

## Contexto

El proyecto necesita un conjunto de datos real, redistribuible y transaccional, con suficientes
uniones, fechas y valores de texto libre para demostrar text-to-SQL, recuperación, evaluación y
seguridad frente a la inyección de prompts. Debe funcionar sin conexión a partir de un artefacto
incluido y no debe exponer datos personales. Las fuentes candidatas se compararon en la sección
de fuentes de datos del plan: World Bank WDI (indicadores macro, no transaccionales), INEC (no se
verificó un CSV directo y estable), el portal CKAN de Ecuador (licencias mixtas por conjunto de
datos) y OCHA/HDX (403 ante descargas automatizadas).

Los datos masivos OCDS de SERCOP para 2021 se publican a través del registro de la Open
Contracting Partnership bajo CC BY 3.0 Ecuador. Contienen 122.277 procesos de contratación,
121.736 adjudicaciones y 293.287 registros de partes, y la política del publicador permite
expresamente la redistribución con un enlace a la fuente. También contienen nombres y RUC de
proveedores, incluidas 6.086 personas naturales.

## Decisión

Adoptar el CSV de SERCOP OCDS 2021 como el único almacén incluido. Consumir seis miembros
(`main`, `awards`, `awards_suppliers`, `contracts`, `parties`, `tender_items`) y fijar sus hashes
SHA-256 porque el tarball de origen se regenera.

Pseudonimizar a los proveedores personas naturales durante el ETL, antes de escribir cualquier
Parquet: el tercer dígito del RUC 0–5 identifica a una persona natural; esos proveedores reciben
un identificador determinista `PN-000001…` (ordenado por RUC) y el nombre visible
`Persona natural PN-xxxxxx`. La provincia y el cantón siguen disponibles para el análisis
agregado. Los proveedores que no son personas naturales conservan su RUC. Las filas se ordenan
por clave y el manifiesto registra hashes, conteos de filas y huellas digitales.

Los 96 identificadores heredados de proveedor que carecen del prefijo `EC-RUC-` no pueden
clasificarse de forma segura y se agrupan en un único proveedor `other` (`ID-UNKNOWN`) con un
nombre neutro. Así se mantiene válida cada clave foránea de adjudicación y se conservan las
10.217 filas de proveedor fijadas, sin publicar identificadores no verificables.

## Consecuencias

* El repositorio incluye unos 4,3 MB de Parquet y funciona por completo sin conexión.
* Los valores reales de texto libre en español ejercitan el sanitizador y la capa semántica
  bilingüe.
* El análisis agregado de personas naturales sigue siendo posible por `supplier_id`, pero los
  nombres no se pueden recuperar a partir del paquete.
* Los 96 proveedores heredados se agregan en un único grupo, así que el análisis por proveedor de
  ese subconjunto pequeño es más grueso; la limitación está documentada en `DATA.md`.
* Las regeneraciones upstream pueden romper los fijados de miembros; `--allow-checksum-drift`
  existe para una reconstrucción revisada, y el paquete confirmado sigue siendo la fuente de
  verdad para las pruebas.
* La licencia exige atribución visible en los README, en la interfaz web, en `data info` y en
  `DATA.md`.

## Alternativas consideradas

* **World Bank WDI**: CC BY 4.0 y estable, pero la forma EAV macro casi no ofrece uniones,
  entidades ni texto libre; rechazada.
* **INEC**: las páginas mencionan CC BY 4.0, pero no se verificó un CSV transaccional directo y
  estable; rechazada por no ser verificable.
* **CKAN de datosabiertos.gob.ec**: las licencias varían por conjunto de datos (`cc-by`, `cc-nc`,
  vacía); no es uniformemente redistribuible; rechazada.
* **Solo datos sintéticos**: seguros y triviales de licenciar, pero pierden el realismo que hace
  creíbles las historias de recuperación, resolución de entidades e inyección; rechazada.
* **Conservar los RUC pero ocultar los nombres**: un RUC sigue identificando a una persona
  natural; rechazada.
