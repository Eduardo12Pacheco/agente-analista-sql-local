"""AskQuestion use case: one-turn memory and LRU(50) sessions (S13)."""

from __future__ import annotations

import json

from sqlagent.adapters.llm.scripted import ScriptedLLM
from sqlagent.application.use_cases.ask import AskQuestion
from sqlagent.domain.models import Language, Status


def final(sql: str = "SELECT COUNT(*) AS n FROM tenders") -> str:
    return json.dumps({"plan": ["count"], "action": "final_sql", "sql": sql})


def narrate() -> str:
    return json.dumps({"answer": "ok"})


def clarify() -> str:
    return json.dumps({"plan": ["ask"], "action": "clarify", "message": "¿Cuál?"})


def _generate_prompts(llm: ScriptedLLM) -> list[str]:
    return [
        str(request.messages[-1]["content"]) for request in llm.calls if request.stage == "generate"
    ]


def test_previous_turn_is_sent_to_generate(make_agent) -> None:
    llm = ScriptedLLM(
        [
            final(),
            narrate(),
            final("SELECT COUNT(*) AS n FROM buyers"),
            narrate(),
        ]
    )
    use_case = AskQuestion(make_agent(llm))
    first = use_case.execute("How many tenders?", session_id="s1")
    second = use_case.execute("And buyers?", session_id="s1")

    assert first.status is Status.OK
    assert second.status is Status.OK
    prompts = _generate_prompts(llm)
    assert "PREVIOUS TURN" not in prompts[0]
    assert "PREVIOUS TURN" in prompts[1]
    assert "SELECT COUNT(*) AS n FROM tenders" in prompts[1]
    assert use_case.sessions == ("s1",)


def test_without_session_id_no_memory_is_sent(make_agent) -> None:
    llm = ScriptedLLM([final(), narrate(), final(), narrate()])
    use_case = AskQuestion(make_agent(llm))
    use_case.execute("How many tenders?")
    use_case.execute("How many tenders again?")

    prompts = _generate_prompts(llm)
    assert "PREVIOUS TURN" not in prompts[1]
    assert use_case.sessions == ()


def test_only_successful_answers_are_remembered(make_agent) -> None:
    llm = ScriptedLLM([clarify(), final(), narrate()])
    use_case = AskQuestion(make_agent(llm))
    first = use_case.execute("Muéstrame el mejor proveedor", session_id="s1")
    second = use_case.execute("¿Cuántos proveedores hay?", session_id="s1")

    assert first.status is Status.CLARIFICATION
    assert second.status is Status.OK
    prompts = _generate_prompts(llm)
    assert "PREVIOUS TURN" not in prompts[1]


def test_sessions_are_an_lru_of_the_configured_capacity(make_agent) -> None:
    llm = ScriptedLLM(
        [final(), narrate(), final(), narrate(), final(), narrate(), final(), narrate()]
    )
    use_case = AskQuestion(make_agent(llm), capacity=2)

    use_case.execute("How many tenders?", session_id="a")
    use_case.execute("How many buyers?", session_id="b")
    assert use_case.sessions == ("a", "b")
    use_case.execute("How many awards?", session_id="c")
    assert use_case.sessions == ("b", "c")
    use_case.execute("How many suppliers?", session_id="a")
    assert use_case.sessions == ("c", "a")


def test_language_override_is_forwarded(make_agent) -> None:
    llm = ScriptedLLM([final(), narrate()])
    answer = AskQuestion(make_agent(llm)).execute("How many tenders?", language=Language.ES)
    assert answer.language is Language.ES
