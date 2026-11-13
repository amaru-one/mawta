"""The question bank (D017): the two scope tools, the fixed out-of-scope phrase written by the
code, and the status of every question, decided from the tools that ran."""

import httpx
import pytest

from chat.status import question_status
from chat.tools.scope import OUT_OF_SCOPE
from tests.chat.conftest import ANA, FakeLLM, Session, text_turn, tool_turn
from tests.chat.test_ask import ask
from tests.conftest import Admin


async def bank_row(admin: Admin, thread_id: str, question: str) -> dict[str, object]:
    """The bank's row of a question of this thread (other tests ask the same words)."""
    row = await (
        await admin.execute(
            "select b.status, b.tool_name from chat.question_bank b"
            " join chat.messages m on m.id = b.message_id"
            " where m.thread_id = %s and b.question = %s",
            (thread_id, question),
        )
    ).fetchone()
    assert row is not None, "no row in the bank"
    return dict(row)


async def test_out_of_scope_is_answered_by_the_code_word_for_word(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM, admin: Admin
):
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(name="fuera_de_alcance"))

    events = await ask(client, me, thread["id"], "¿Qué hay de almuerzo hoy?")

    assert "".join(e["delta"] for e in events if e["tipo"] == "texto") == OUT_OF_SCOPE
    assert len(fake_llm.calls) == 1, "the model is not asked to write the answer"
    messages = (await client.get(f"/threads/{thread['id']}/messages", headers=me)).json()
    assert messages[-1]["blocks"] == [{"tipo": "texto", "md": OUT_OF_SCOPE}]
    assert await bank_row(admin, thread["id"], "¿Qué hay de almuerzo hoy?") == {
        "status": "fuera_de_alcance",
        "tool_name": None,
    }
    # The next question still carries a well-formed history (tool call + tool result + answer).
    fake_llm.script(text_turn("Claro."))
    await ask(client, me, thread["id"], "Ok, gracias")
    roles = [m["role"] for m in fake_llm.calls[-1]]
    assert roles == ["user", "assistant", "tool", "assistant", "user"]


async def test_a_missing_tool_is_recorded_with_its_topic(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM, admin: Admin
):
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(
        tool_turn(name="sin_herramienta", arguments='{"tema": "asistencia de 1A"}'),
        text_turn("Mawta todavía no registra asistencia."),
    )

    events = await ask(client, me, thread["id"], "¿Quiénes faltan mucho en 1A?")

    assert "Revisando qué puedo consultar…" in [e.get("texto") for e in events]
    assert await bank_row(admin, thread["id"], "¿Quiénes faltan mucho en 1A?") == {
        "status": "necesita_tool",
        "tool_name": "asistencia de 1A",
    }


async def test_an_answered_question_names_its_tool(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM, admin: Admin
):
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(), text_turn("Tres secciones."))
    await ask(client, me, thread["id"], "¿Qué secciones hay?")
    assert await bank_row(admin, thread["id"], "¿Qué secciones hay?") == {
        "status": "respondida",
        "tool_name": "datos_del_colegio",
    }


async def test_a_clarification_and_a_toolless_answer_are_partial(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM, admin: Admin
):
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(
        tool_turn(name="historial_del_alumno", arguments='{"alumno": "x"}'),
        text_turn("¿A quién te refieres?"),
    )
    await ask(client, me, thread["id"], "¿Cómo va x?")
    assert await bank_row(admin, thread["id"], "¿Cómo va x?") == {
        "status": "parcial",
        "tool_name": "historial_del_alumno",
    }
    fake_llm.script(text_turn("Creo que bien."))
    await ask(client, me, thread["id"], "¿Y en general?")
    assert await bank_row(admin, thread["id"], "¿Y en general?") == {
        "status": "parcial",
        "tool_name": None,
    }


@pytest.mark.parametrize(
    ("calls", "failed", "expected"),
    [
        ([], False, ("parcial", None)),
        (
            [{"name": "fuera_de_alcance", "input": {}, "result": {}}],
            False,
            ("fuera_de_alcance", None),
        ),
        (
            [{"name": "sin_herramienta", "input": {"tema": " notas "}, "result": {}}],
            False,
            ("necesita_tool", "notas"),
        ),
        ([{"name": "sin_herramienta", "input": {}, "result": {}}], False, ("necesita_tool", None)),
        (
            [{"name": "alumnos_con_c", "input": {}, "result": {"alumnos_con_C": 2}}],
            False,
            ("respondida", "alumnos_con_c"),
        ),
        (
            [{"name": "alumnos_con_c", "input": {}, "result": {"alumnos_con_C": 2}}],
            True,
            ("parcial", "alumnos_con_c"),
        ),
        (
            [{"name": "alumnos_con_c", "input": {}, "result": {"sin_datos": "…"}}],
            False,
            ("parcial", "alumnos_con_c"),
        ),
        (
            [{"name": "alumnos_con_c", "input": {}, "result": {"error": "x"}, "is_error": True}],
            False,
            ("parcial", "alumnos_con_c"),
        ),
        (
            [
                {"name": "datos_del_colegio", "input": {}, "result": {}},
                {"name": "sin_herramienta", "input": {"tema": "asistencia"}, "result": {}},
            ],
            False,
            ("necesita_tool", "asistencia"),
        ),
    ],
)
def test_the_status_follows_the_tools_that_ran(calls, failed, expected):
    assert question_status(calls, failed=failed) == expected
