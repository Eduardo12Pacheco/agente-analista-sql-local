"""Bilingual chrome dictionaries for the web UI (S29/D23).

The dictionaries are plain data so tests can prove that both languages expose the
same key set.  Questions and answer narratives are never translated here: those
come from the user and the model, while only the surrounding chrome is localized.
"""

from __future__ import annotations

from typing import Final, Literal

type LanguageCode = Literal["en", "es"]

LANGUAGES: Final[tuple[LanguageCode, ...]] = ("en", "es")
DEFAULT_LANGUAGE: Final[LanguageCode] = "es"

_EN: Final[dict[str, str]] = {
    "app_title": "Local SQL Analyst",
    "app_tagline": "Ask the SERCOP procurement warehouse in English or Spanish.",
    "skip_to_content": "Skip to content",
    "model_label": "Model",
    "backend_label": "Backend",
    "ollama_ok": "Ollama ready",
    "ollama_down": "Ollama offline",
    "demo_banner": "Demo mode: answers come from recorded model outputs and work offline.",
    "lang_toggle_label": "Switch language to Spanish",
    "lang_toggle_text": "ES",
    "theme_toggle": "Toggle light and dark theme",
    "theme_light": "Light",
    "theme_dark": "Dark",
    "empty_title": "Ask a question about Ecuadorian public procurement",
    "empty_body": (
        "The analyst plans, writes read-only SQL against the bundled SERCOP 2021 "
        "warehouse, executes it and charts the result. No account or API key needed."
    ),
    "examples_title": "Try an example",
    "example_1": "What percentage of tenders were competitive?",
    "example_2": "Top 10 suppliers by total awarded amount",
    "example_3": "How many tenders were for public works?",
    "example_4": "¿Cuáles son las 5 provincias con más procesos?",
    "example_5": "¿Cuál es el monto total adjudicado en dólares?",
    "example_6": "¿Cuántos procesos publicó el IESS?",
    "question_label": "Your question",
    "question_placeholder": "How many tenders are in the database?",
    "send": "Ask",
    "composer_hint": "Enter sends · Shift+Enter adds a new line",
    "no_js_hint": "JavaScript is disabled: submitting shows the full answer on a new page.",
    "running": "Working…",
    "phase_understand": "Understanding",
    "phase_retrieve": "Retrieving schema",
    "phase_generate": "Generating SQL",
    "phase_validate": "Validating",
    "phase_execute": "Executing",
    "phase_chart": "Charting",
    "phase_narrate": "Writing the answer",
    "phase_done": "Done",
    "phase_repair": "Repairing SQL",
    "phase_tool": "Looking up values",
    "retrieval_tables": "Tables in context",
    "status_ok": "Answer",
    "status_clarification": "Clarification",
    "status_refused": "Refused",
    "status_failed": "Could not answer",
    "sql_title": "SQL",
    "copy_sql": "Copy SQL",
    "copied": "Copied",
    "readonly_badge": "read-only",
    "validated_badge": "validated",
    "limit_badge": "LIMIT {limit}",
    "result_title": "Result",
    "rows_count": "{count} rows",
    "truncated_notice": "Showing the first {count} rows; the query result was truncated.",
    "chart_title": "Chart",
    "chart_aria": "Chart of the query result",
    "chart_why": "why this chart",
    "chart_fallback": "Show the chart data as a table",
    "export_csv": "Download CSV",
    "trace_title": "Trace",
    "trace_llm_calls": "LLM calls",
    "trace_tokens": "Tokens",
    "trace_tables": "Retrieved tables",
    "trace_attempts": "Attempts",
    "trace_guardrails": "Guardrail events",
    "trace_injections": "Injection flags",
    "none": "none",
    "clarification_title": "I need a more specific question",
    "refusal_title": "That request is out of scope",
    "failed_title": "The analyst could not complete this run",
    "error_title": "Something went wrong",
    "error_hint": "Check the model backend with `sqlagent doctor`, then try again.",
    "error_retry": "Try again",
    "schema_title": "Data drawer",
    "schema_tables": "Tables and columns",
    "schema_attribution": "Data attribution",
    "footer_attribution": (
        "Contains data from SERCOP, Ecuador (datosabiertos.compraspublicas.gob.ec), "
        "CC BY 3.0 EC; filtered, normalised and pseudonymised."
    ),
}

_ES: Final[dict[str, str]] = {
    "app_title": "Analista SQL Local",
    "app_tagline": ("Consulta el almacén de contratación pública del SERCOP en español o inglés."),
    "skip_to_content": "Ir al contenido",
    "model_label": "Modelo",
    "backend_label": "Backend",
    "ollama_ok": "Ollama disponible",
    "ollama_down": "Ollama no disponible",
    "demo_banner": (
        "Modo demo: las respuestas provienen de salidas grabadas y funcionan sin conexión."
    ),
    "lang_toggle_label": "Cambiar el idioma a inglés",
    "lang_toggle_text": "EN",
    "theme_toggle": "Cambiar entre tema claro y oscuro",
    "theme_light": "Claro",
    "theme_dark": "Oscuro",
    "empty_title": "Pregunta sobre la contratación pública de Ecuador",
    "empty_body": (
        "El analista planifica, escribe SQL de solo lectura sobre el almacén SERCOP 2021, "
        "lo ejecuta y grafica el resultado. No necesita cuenta ni clave de API."
    ),
    "examples_title": "Prueba un ejemplo",
    "example_1": "¿Cuáles son las 5 provincias con más procesos?",
    "example_2": "¿Cuál es el monto total adjudicado en dólares?",
    "example_3": "¿Cuántos procesos publicó el IESS?",
    "example_4": "How many tenders were for public works?",
    "example_5": "Top 10 suppliers by total awarded amount",
    "example_6": "What percentage of tenders were competitive?",
    "question_label": "Tu pregunta",
    "question_placeholder": "¿Cuántos procesos de contratación hay?",
    "send": "Preguntar",
    "composer_hint": "Enter envía · Shift+Enter agrega una línea",
    "no_js_hint": (
        "JavaScript está desactivado: al enviar verás la respuesta completa en otra página."
    ),
    "running": "Trabajando…",
    "phase_understand": "Entendiendo",
    "phase_retrieve": "Recuperando esquema",
    "phase_generate": "Generando SQL",
    "phase_validate": "Validando",
    "phase_execute": "Ejecutando",
    "phase_chart": "Graficando",
    "phase_narrate": "Redactando",
    "phase_done": "Listo",
    "phase_repair": "Reparando SQL",
    "phase_tool": "Buscando valores",
    "retrieval_tables": "Tablas en contexto",
    "status_ok": "Respuesta",
    "status_clarification": "Aclaración",
    "status_refused": "Rechazado",
    "status_failed": "No se pudo responder",
    "sql_title": "SQL",
    "copy_sql": "Copiar SQL",
    "copied": "Copiado",
    "readonly_badge": "solo lectura",
    "validated_badge": "validado",
    "limit_badge": "LÍMITE {limit}",
    "result_title": "Resultado",
    "rows_count": "{count} filas",
    "truncated_notice": "Se muestran las primeras {count} filas; el resultado fue truncado.",
    "chart_title": "Gráfico",
    "chart_aria": "Gráfico del resultado de la consulta",
    "chart_why": "por qué este gráfico",
    "chart_fallback": "Ver los datos del gráfico como tabla",
    "export_csv": "Descargar CSV",
    "trace_title": "Traza",
    "trace_llm_calls": "Llamadas al LLM",
    "trace_tokens": "Tokens",
    "trace_tables": "Tablas recuperadas",
    "trace_attempts": "Intentos",
    "trace_guardrails": "Eventos de guardrail",
    "trace_injections": "Marcas de inyección",
    "none": "ninguna",
    "clarification_title": "Necesito una pregunta más específica",
    "refusal_title": "Esa solicitud está fuera de alcance",
    "failed_title": "El analista no pudo completar esta ejecución",
    "error_title": "Algo salió mal",
    "error_hint": "Revisa el backend del modelo con `sqlagent doctor` y vuelve a intentarlo.",
    "error_retry": "Reintentar",
    "schema_title": "Panel de datos",
    "schema_tables": "Tablas y columnas",
    "schema_attribution": "Atribución de datos",
    "footer_attribution": (
        "Contiene datos del SERCOP, Ecuador (datosabiertos.compraspublicas.gob.ec), "
        "CC BY 3.0 EC; filtrados, normalizados y pseudonimizados."
    ),
}

_CATALOGS: Final[dict[str, dict[str, str]]] = {"en": _EN, "es": _ES}

PHASE_KEYS: Final[dict[str, str]] = {
    "UNDERSTAND": "phase_understand",
    "RETRIEVE": "phase_retrieve",
    "GENERATE": "phase_generate",
    "TOOL": "phase_tool",
    "VALIDATE": "phase_validate",
    "EXECUTE": "phase_execute",
    "REPAIR": "phase_repair",
    "CHART": "phase_chart",
    "NARRATE": "phase_narrate",
    "DONE": "phase_done",
}


def normalize_language(value: str | None) -> LanguageCode:
    """Map a user/header value to a supported chrome language."""

    lowered = (value or "").strip().lower()
    if lowered.startswith("es"):
        return "es"
    if lowered.startswith("en"):
        return "en"
    return "en"


def catalog(language: str) -> dict[str, str]:
    """Return a copy of one language's dictionary (fallback: English)."""

    return dict(_CATALOGS.get(normalize_language(language), _EN))


def translate(language: str, key: str, **values: object) -> str:
    """Translate ``key`` and format ``{placeholders}``; unknown keys pass through."""

    template = _CATALOGS.get(normalize_language(language), _EN).get(key)
    if template is None:
        return key
    if not values:
        return template
    try:
        return template.format(**values)
    except (KeyError, IndexError):
        return template


def phase_label(language: str, phase: str) -> str:
    """Human label for one state-machine phase (S29 stepper)."""

    key = PHASE_KEYS.get(phase.upper())
    return translate(language, key) if key else phase


def example_questions(language: str) -> tuple[str, ...]:
    """Six example chips, three per language, alternating from the active one."""

    language = normalize_language(language)
    first = (1, 2, 3) if language == "es" else (4, 5, 6)
    second = (4, 5, 6) if language == "es" else (1, 2, 3)
    return tuple(translate(language, f"example_{index}") for index in (*first, *second))


__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "PHASE_KEYS",
    "LanguageCode",
    "catalog",
    "example_questions",
    "normalize_language",
    "phase_label",
    "translate",
]
