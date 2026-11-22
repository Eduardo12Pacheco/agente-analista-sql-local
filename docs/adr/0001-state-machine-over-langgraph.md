# ADR-0001: Una máquina de estados simple en Python en lugar de LangGraph

- **Estado:** Aceptada
- **Fecha:** 2026-11-20
- **Decisores:** Eduardo Pacheco

## Contexto

El agente de análisis es un flujo de trabajo explícito y acotado: entender la pregunta,
recuperar el contexto del esquema, generar SQL, validarlo, ejecutarlo, reparar hasta dos
veces, elegir un gráfico y narrar. Tiene diez fases, dos bucles pequeños y límites estrictos
en llamadas a herramientas, reparaciones y llamadas totales al LLM. El flujo debe ser
determinista en las pruebas con salidas predefinidas del LLM, transmitir eventos de fase a la
interfaz web y producir una traza tipada que el arnés de evaluación pueda puntuar.

LangGraph 1.2.24 era la alternativa evidente, pero arrastra `langchain-core` 1.8.4 y un árbol
de dependencias transitivas. Ese árbol dominaría el tamaño de la instalación y la superficie
de la cadena de suministro de una herramienta local-first, y sus abstracciones aun así
necesitarían código propio para los límites y la traza tipada que requerimos.

## Decisión

Implementar el agente como una máquina de estados simple en Python dentro de
`src/sqlagent/application/agent/`. Una tabla de manejadores asocia cada `Phase` con una
función; la máquina mantiene los contadores explícitos (`tool_calls <= 3`, `repairs <= 2`, un
reintento de protocolo por llamada al LLM y un tope de 12 llamadas al LLM por pregunta) y
emite `AgentEvent` tipados. El grafo se documenta con el diagrama de estados Mermaid en
`docs/ARCHITECTURE.md`.

## Consecuencias

- Cero dependencias de ejecución más allá del conjunto pequeño y auditado de `pyproject.toml`.
- Las pruebas pueden recorrer cada rama con `ScriptedLLM` y verificar números exactos de
  llamadas, lo que hace barato verificar las propiedades de terminación y de límites.
- Los eventos de fase, las trazas y el mapeo de errores son de primera clase, en lugar de
  callbacks de un framework.
- Renunciamos al checkpointing de LangGraph, a sus herramientas visuales de grafos y a sus
  integraciones del ecosistema. La aplicación es de un solo turno con un turno previo de
  memoria, así que el checkpointing no es un requisito. Si alguna vez se necesitan flujos
  duraderos de varios pasos, la tabla de manejadores es un módulo acotado que se puede
  reemplazar.

## Alternativas consideradas

- **LangGraph 1.2.24:** rechazada por el árbol transitivo de `langchain-core` 1.8.4, el peso de
  la instalación y la indirección, frente a un grafo de diez estados.
- **Bucles anidados ad hoc:** rechazados porque la cobertura de ramas, los límites y la
  semántica de la traza son difíciles de demostrar; una tabla de manejadores mantiene todo
  explícito.
- **Un motor de flujos de trabajo genérico (Temporal, Prefect):** rechazado por estar orientado
  a servidores y por ser incompatible con la restricción local-first, sin servidores.
