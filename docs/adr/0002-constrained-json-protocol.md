# ADR-0002: Protocolo JSON restringido en lugar de llamadas a herramientas nativas del proveedor

- **Estado:** Aceptada
- **Fecha:** 2026-11-20
- **Decisores:** Eduardo Pacheco

## Contexto

El agente necesita que el modelo elija entre cuatro acciones (`final_sql`, `lookup_values`,
`clarify`, `refuse`) y que devuelva un plan breve. El backend por defecto es un modelo local
pequeño servido por Ollama. Existen las llamadas a herramientas nativas del proveedor, pero los
modelos pequeños con frecuencia emiten mal esas llamadas o inventan nombres de herramientas, y
el formato exacto del prompt cambia entre backends. También necesitamos prompts idénticos para
reproducir de forma determinista desde las grabaciones, y los dobles de prueba predefinidos
deben ejercitar el mismo protocolo.

Ollama 0.40.x admite la decodificación restringida por JSON Schema mediante el campo `format`
de `/api/chat`, lo que puede eliminar la mayoría de los errores de sintaxis sin ninguna
maquinaria de herramientas específica del proveedor.

## Decisión

Definir un objeto JSON plano, validado con un JSON Schema (y con un modelo Pydantic en la capa
de aplicación), con estos campos:

- `plan[]`: de uno a cinco pasos breves (como máximo 160 caracteres cada uno).
- `action`: una de `final_sql`, `lookup_values`, `clarify`, `refuse`.
- `sql`, `lookup`, `message`: campos condicionales requeridos por la acción elegida.

El mismo esquema se pasa al campo `format` de Ollama, lo usan las pruebas con `ScriptedLLM` y
se incluye en las cassettes grabadas. Un JSON inválido o una violación del esquema reciben un
reintento de protocolo; después, una respuesta `FAILED` controlada. El ciclo despacha él mismo
`lookup_values`; el modelo nunca ejecuta herramientas directamente.

## Consecuencias

- Funciona igual entre modelos de Ollama y dobles de prueba; no depende del soporte de llamadas
  a herramientas nativas.
- El plan es un campo de la misma salida en lugar de una segunda llamada al LLM, lo que ahorra
  un viaje de ida y vuelta y mantiene menor la latencia.
- El prompt y el esquema forman parte de la clave de la cassette, así que los cambios de
  protocolo invalidan visiblemente las grabaciones en lugar de cambiar el comportamiento en
  silencio.
- Renunciamos a la orquestación automática de herramientas del proveedor y debemos analizar y
  validar cada respuesta nosotros mismos. El esquema es pequeño y la validación está probada.
- Un modelo que no pueda seguir el formato JSON puede necesitar el único reintento; después de
  eso, la respuesta es un fallo amable en lugar de una excepción.

## Alternativas consideradas

- **Llamadas a herramientas nativas del proveedor:** rechazadas por la inconsistencia entre
  backends, el mal comportamiento en modelos pequeños y la reproducción determinista más difícil.
- **Texto libre con extracción por expresiones regulares:** rechazado por frágil e inseguro;
  invita a SQL malformado y a una selección de acción ambigua.
- **Una llamada de planificación separada:** rechazada porque duplica la latencia y el costo por
  un plan que solo alimenta la traza y la interfaz.
