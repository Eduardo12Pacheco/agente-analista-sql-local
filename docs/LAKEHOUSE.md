# Adaptador de lakehouse externo

`sqlagent` normalmente responde preguntas sobre su almacén SERCOP incluido. Con un **manifiesto de
lakehouse** puede, en cambio, leer un archivo DuckDB producido por otro proyecto local, con la
misma conexión bloqueada y de solo lectura, la misma política SQL y el mismo ciclo del agente. El
adaptador es opcional y no tiene ninguna dependencia de ejecución con el proyecto productor: el
manifiesto es un archivo JSON simple con un esquema documentado y versionado.

- Contrato: `sqlagent.lakehouse-manifest/v1`
- JSON Schema: [`docs/lakehouse-manifest.schema.json`](lakehouse-manifest.schema.json)
- Ejemplo: [`docs/examples/lakehouse-manifest.example.json`](examples/lakehouse-manifest.example.json)

## Inicio rápido

```bash
# Validate a manifest and inspect its database before asking anything.
sqlagent doctor --offline --manifest /path/to/manifest.json

# Ask over the external warehouse (Ollama or replay; the bundled benchmark does
# not apply to external warehouses).
sqlagent ask --manifest /path/to/manifest.json "How many rows are in the sales table?"

# Or point the web chat at it.
sqlagent serve --manifest /path/to/manifest.json --port 17080
```

El mismo valor se puede proporcionar mediante el entorno:

```bash
export SQLAGENT_LAKEHOUSE_MANIFEST=/path/to/manifest.json
sqlagent doctor --offline
```

Cuando se define `--manifest` o `SQLAGENT_LAKEHOUSE_MANIFEST`, reemplaza por completo al paquete
Parquet incluido. Los códigos de salida son los habituales: `2` para una configuración o un
manifiesto no válidos, `3` para un archivo DuckDB ausente o alterado, o un problema del entorno, y
`0` en caso de éxito.

## Campos del manifiesto

| Campo | Tipo | Obligatorio | Significado |
|---|---|---|---|
| `schema` | cadena | sí | Exactamente `sqlagent.lakehouse-manifest/v1`. |
| `name` | cadena | sí | Nombre legible del lakehouse, mostrado por `doctor`. |
| `generated_at` | fecha-hora ISO-8601 | sí | Momento en que se produjo el par base de datos/manifiesto. |
| `duckdb_file` | ruta relativa | sí | Archivo DuckDB, relativo al directorio del manifiesto. Las rutas absolutas y los escapes con `..` se rechazan. |
| `sha256` | 64 caracteres hex | sí | SHA-256 de `duckdb_file`; se verifica antes de abrir el archivo. |
| `tables` | arreglo (≥ 1) | sí | Tablas documentadas, en el orden del prompt. |
| `tables[].name` | identificador SQL | sí | Nombre de la tabla en el archivo DuckDB. |
| `tables[].description` | cadena | sí | Descripción de una línea usada en los prompts en EN y ES. |
| `tables[].columns` | arreglo (≥ 1) | sí | Columnas documentadas. |
| `tables[].columns[].name` | identificador SQL | sí | Nombre de la columna. |
| `tables[].columns[].type` | cadena | sí | Tipo de DuckDB, p. ej. `VARCHAR`, `BIGINT`, `DOUBLE`, `DATE`. |
| `tables[].columns[].description` | cadena | sí | Descripción de una línea usada en los prompts en EN y ES. |
| `tables[].columns[].synonyms` | arreglo de cadenas | no | Términos bilingües de recuperación (por defecto vacío). |
| `tables[].columns[].lookupable` | booleano | no | Permite `lookup_values` en esta columna de texto (por defecto `false`). |
| `tables[].columns[].samples` | arreglo de cadenas | no | Valores de muestra de baja cardinalidad para la recuperación. |
| `relationships` | arreglo | no | Rutas de unión como `{"from": "table.column", "to": "table.column"}`. |
| `language` | `es`, `en`, `multi` | no | Indicación del idioma de la documentación (por defecto `multi`). |

El manifiesto es la **única** fuente de esquema para un almacén externo: las métricas, las entradas
del glosario y los ejemplos few-shot de los recursos incluidos quedan deshabilitados, porque el
contrato no los incluye.

## Cómo emite un manifiesto un proyecto hermano

1. Escribe el archivo DuckDB de forma determinista (orden fijo, sin marcas de tiempo) y cierra
   todas las conexiones.
2. Calcula su hash con una herramienta disponible en Linux, macOS y Windows. En Linux/macOS:

   ```bash
   sha256sum warehouse/lakehouse.duckdb
   ```

   En PowerShell de Windows:

   ```powershell
   (Get-FileHash -Algorithm SHA256 warehouse\lakehouse.duckdb).Hash.ToLower()
   ```

   O desde Python, de forma multiplataforma:

   ```bash
   python -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('warehouse/lakehouse.duckdb').read_bytes()).hexdigest())"
   ```

3. Genera el archivo JSON (el ejemplo siguiente también está incluido como
   `docs/examples/lakehouse-manifest.example.json`):

   ```json
   {
     "schema": "sqlagent.lakehouse-manifest/v1",
     "name": "example-lakehouse",
     "generated_at": "2026-11-20T12:00:00Z",
     "duckdb_file": "example.duckdb",
     "sha256": "<sha256 of example.duckdb>",
     "tables": [
       {
         "name": "countries",
         "description": "Countries with their region.",
         "columns": [
           {
             "name": "country_code",
             "type": "VARCHAR",
             "description": "ISO 3166-1 alpha-3 country code.",
             "synonyms": ["pais", "codigo de pais"],
             "lookupable": true,
             "samples": ["ECU", "PER"]
           }
         ]
       }
     ],
     "relationships": [],
     "language": "en"
   }
   ```

4. Valida el manifiesto localmente antes de publicarlo: `sqlagent doctor --offline --manifest <ruta>`
   muestra el nombre del manifiesto y el número de tablas, y después abre la base de datos en solo
   lectura e informa los conteos de filas. La suite de pruebas incluida valida en cada ejecución el
   ejemplo confirmado y el JSON Schema.

No se importa ningún otro repositorio en tiempo de ejecución; la integración se hace únicamente a
través de este artefacto documentado. El productor y el consumidor pueden evolucionar de forma
independiente mientras se respete el contrato `v1`.

## Validación y seguridad

Antes de ejecutar cualquier consulta, el adaptador comprueba:

- la sintaxis JSON y el esquema `sqlagent.lakehouse-manifest/v1` (modelo de pydantic,
  `extra="forbid"`), con mensajes `ConfigError` legibles;
- que `duckdb_file` es relativo, no escapa del directorio del manifiesto y existe;
- que el SHA-256 del archivo es igual a `sha256`; una discrepancia aborta con
  `lakehouse SHA-256 mismatch: manifest expects …, file has …` y la CLI sale con código 3;
- que ninguna tabla usa un nombre de sistema reservado (`information_schema`, `sqlite_master`, o
  cualquier nombre de catálogo `duckdb_*` / `pg_*`);
- que cada tabla documentada existe en el archivo, y cada columna documentada existe con el tipo
  declarado (las columnas ausentes o con tipo distinto se rechazan);
- que la lista blanca de tablas del manifiesto se convierte en la lista blanca de tablas de
  `SqlPolicy`, de modo que el SQL no pueda llegar a tablas no documentadas.

Después, la base de datos se abre exactamente como el almacén incluido: `read_only=True`, carga y
autoinstalación de extensiones desactivadas, acceso externo desactivado, límites de memoria e hilos
aplicados y `lock_configuration=true` al final. `sqlagent doctor` también respeta `--manifest`, de
modo que un artefacto no válido o alterado se detecta antes de que arranque el agente.

## Limitaciones

- El benchmark (`sqlagent eval`) está definido solo para el almacén SERCOP incluido; no se puntúa
  con datos externos.
- Los almacenes externos no tienen métricas, glosario ni ejemplos few-shot, así que la recuperación
  y la narración dependen solo de las descripciones del manifiesto.
- El manifiesto describe un archivo DuckDB, no un servidor de base de datos en vivo; el archivo debe
  ser local y permanecer estable mientras dure una ejecución.
- Solo las columnas documentadas aparecen en los prompts; las columnas no documentadas del archivo
  se rechazan por la política SQL aunque existan físicamente.
