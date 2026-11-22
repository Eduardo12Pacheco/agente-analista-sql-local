# ADR-0008: Paquete Parquet y almacén DuckDB materializado

## Contexto

La aplicación debe arrancar sin conexión en Linux, Windows y macOS, exponer al agente un almacén
analítico de solo lectura y ser lo bastante pequeña como para distribuirse en un wheel. Entre las
opciones estaban un paquete CSV, un archivo `.duckdb` precompilado, o Parquet más un paso de
materialización en el primer uso. Un archivo DuckDB precompilado depende del formato de
almacenamiento y se reescribiría con cada actualización de DuckDB; el CSV es voluminoso, lento y
pierde los tipos. El agente nunca debe tener una conexión con permisos de escritura.

## Decisión

Distribuir seis archivos Parquet (zstd nivel 19) más `MANIFEST.json` en
`src/sqlagent/resources/warehouse/`. En el primer uso, `ensure_warehouse(settings)` materializa
los archivos en `<data_dir>/warehouse-<manifest-sha8>.duckdb` con las claves primarias y foráneas
declaradas. El nombre del archivo incorpora el hash del manifiesto, así que un paquete reconstruido
produce una base de datos nueva, mientras que una existente se reutiliza sin migración.

La materialización es atómica: la base de datos se crea en un archivo temporal dentro del mismo
directorio y se mueve con `os.replace` a su sitio solo cuando existen todas las tablas y
restricciones. La conexión que usa el agente se abre entonces con `read_only=True`; el
materializador es el único que escribe. El manifiesto guarda los hashes de los archivos, los
conteos de filas, las huellas monetarias y los conteos de claves distintas, de modo que
`sqlagent data verify` pueda detectar un paquete obsoleto o corrupto.

## Consecuencias

* El wheel se mantiene por debajo del presupuesto de tamaño y es portable entre versiones de DuckDB.
* El primer uso cuesta una materialización (medida en unos 2–5 s en la máquina de referencia, con
  una aserción de ≤ 30 s en las pruebas); los inicios posteriores reutilizan el archivo.
* Un cambio en el paquete invalida solo la base de datos derivada, no los datos del usuario.
* Cualquier proceso que pueda escribir en el directorio de datos del usuario puede manipular el
  archivo materializado; el agente sigue abriéndolo en solo lectura y aplica el bloqueo D15, y
  `data verify` puede reconstruirlo a partir del Parquet confirmado.
* Las restricciones de DuckDB se declaran, pero las claves foráneas no se aplican durante la
  inserción; una prueba de integración comprueba la existencia de registros huérfanos en su lugar.

## Alternativas consideradas

* **`.duckdb` precompilado en el wheel**: el artefacto más grande, atado a una versión de
  almacenamiento de DuckDB, y más difícil de inspeccionar o verificar en git; rechazada.
* **Paquete CSV leído en cada inicio**: no hay artefacto binario, pero es lento, no tiene tipos y es
  aproximadamente un orden de magnitud más grande; rechazada.
* **SQLite**: está ampliamente disponible, pero ofrece un SQL analítico más débil (ventanas,
  `date_trunc`, funciones de lista) y no tiene lector nativo de Parquet; rechazada.
* **Materializar en el directorio del paquete**: rompe las instalaciones de solo lectura y
  contamina site-packages; rechazada.
* **Nombre de base de datos sin versión**: obligaría a detectar cambios del paquete en cada inicio
  o a servir datos obsoletos en silencio; rechazada.
