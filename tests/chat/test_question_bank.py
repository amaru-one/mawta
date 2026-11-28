"""The question bank: the two scope tools, the fixed out-of-scope phrase written by the
code, and the status of every question, decided from the tools that ran in the answer and, for a
follow-up, in the thread before it."""

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


async def test_a_follow_up_answered_from_the_thread_is_answered(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM, admin: Admin
):
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(
        tool_turn(name="resumen_de_niveles"),
        text_turn("En el Bimestre III hay 18 C."),
        text_turn("De esas, Matemática tiene 6."),
    )
    await ask(client, me, thread["id"], "¿Cuántas C hay?")
    await ask(client, me, thread["id"], "¿Y cuántas en matemática?")

    assert await bank_row(admin, thread["id"], "¿Y cuántas en matemática?") == {
        "status": "respondida",
        "tool_name": None,
    }


async def test_a_clarification_the_model_resolves_itself_is_answered(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM, admin: Admin
):
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(
        tool_turn("call_1", '{"area": "robótica"}', name="alumnos_con_c"),
        tool_turn("call_2", "{}", name="alumnos_con_c"),
        text_turn("No hay robótica; en todo el colegio, en el Bimestre III…"),
    )
    await ask(client, me, thread["id"], "¿Jalados en robótica?")

    assert await bank_row(admin, thread["id"], "¿Jalados en robótica?") == {
        "status": "respondida",
        "tool_name": "alumnos_con_c",
    }


CLEAN = {"name": "resumen_de_niveles", "input": {}, "result": {"alumnos_con_C": 2}}
OPTIONS = {"name": "alumnos_con_c", "input": {}, "result": {"necesita_aclaracion": "…"}}
NO_DATA = {"name": "comparar_periodos", "input": {}, "result": {"sin_datos": "…"}}


@pytest.mark.parametrize(
    ("calls", "earlier", "failed", "expected"),
    [
        # A follow-up with no tool rests on a clean result of the thread.
        ([], [CLEAN], False, ("respondida", None)),
        ([], [OPTIONS], False, ("parcial", None)),
        ([], [NO_DATA, CLEAN], False, ("respondida", None)),
        ([], [CLEAN], True, ("parcial", None)),
        ([], [{"name": "sin_herramienta", "input": {}, "result": {}}], False, ("parcial", None)),
        # Several tools: a clean data call backs the answer even if a later exploratory call found
        # no data, unless the last call failed or asked to clarify; the first names the tool.
        ([NO_DATA, CLEAN], [], False, ("respondida", "comparar_periodos")),
        ([CLEAN, NO_DATA], [], False, ("respondida", "resumen_de_niveles")),
        ([OPTIONS, CLEAN], [], False, ("respondida", "alumnos_con_c")),
        ([CLEAN, OPTIONS], [], False, ("parcial", "resumen_de_niveles")),
        ([CLEAN, {**CLEAN, "is_error": True}], [], False, ("parcial", "resumen_de_niveles")),
        # The scope tools still win, whatever the thread holds.
        ([{"name": "fuera_de_alcance", "input": {}, "result": {}}], [CLEAN], False,
         ("fuera_de_alcance", None)),
        ([CLEAN, {"name": "sin_herramienta", "input": {"tema": "asistencia"}, "result": {}}],
         [CLEAN], False, ("necesita_tool", "asistencia")),
    ],
)  # fmt: skip
def test_the_status_of_follow_ups_and_chained_tools(calls, earlier, failed, expected):
    assert question_status(calls, failed=failed, earlier=earlier) == expected


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
