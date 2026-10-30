"""A question streams protocol v1 events and both messages are saved."""

import json
from typing import Any

import httpx
import pytest

from tests.conftest import (
    TENANT_A,
    TENANT_B,
    USER_FLORES,
    USER_QUISPE,
    FakeLLM,
    MakeToken,
    bearer,
    text_turn,
    tool_turn,
)


def parse_sse(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for chunk in body.replace("\r\n", "\n").split("\n\n"):
        data = [
            line[len("data:") :].strip() for line in chunk.split("\n") if line.startswith("data:")
        ]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


async def ask(
    client: httpx.AsyncClient, headers: dict[str, str], thread_id: str, text: str
) -> list[dict[str, Any]]:
    response = await client.post(
        f"/threads/{thread_id}/messages", json={"texto": text}, headers=headers
    )
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


async def test_a_question_uses_the_tool_and_streams_the_answer(
    client: httpx.AsyncClient, make_token: MakeToken, fake_llm: FakeLLM
):
    me = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(
        tool_turn(), text_turn("Tu colegio tiene tres secciones: 2do A, 3ro A y 5to B.")
    )

    events = await ask(client, me, thread["id"], "¿Qué secciones tiene mi colegio?")

    assert all(e["version"] == 1 for e in events)
    kinds = [e["tipo"] for e in events]
    assert kinds[0] == "estado" and kinds[-1] == "fin"
    assert "Consultando los datos del colegio…" in [e.get("texto") for e in events]
    table = next(e for e in events if e["tipo"] == "tabla")
    assert [row[1] for row in table["filas"]] == ["2do A", "3ro A", "5to B"]
    answer = "".join(e["delta"] for e in events if e["tipo"] == "texto")
    assert answer == "Tu colegio tiene tres secciones: 2do A, 3ro A y 5to B."
    assert kinds.index("tabla") < kinds.index("texto")

    messages = (await client.get(f"/threads/{thread['id']}/messages", headers=me)).json()
    assert [m["author"] for m in messages] == ["director", "mawta"]
    assert messages[0]["blocks"] == [{"tipo": "texto", "md": "¿Qué secciones tiene mi colegio?"}]
    assert [b["tipo"] for b in messages[1]["blocks"]] == ["tabla", "texto"]
    assert str(messages[1]["id"]) == events[-1]["message_id"]

    threads = (await client.get("/threads", headers=me)).json()
    assert (
        next(t for t in threads if t["id"] == thread["id"])["title"]
        == "¿Qué secciones tiene mi colegio?"
    )


async def test_the_next_question_carries_the_history(
    client: httpx.AsyncClient, make_token: MakeToken, fake_llm: FakeLLM
):
    me = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(), text_turn("Una sección."), text_turn("Es de turno mañana."))

    await ask(client, me, thread["id"], "¿Cuántas secciones hay?")
    await ask(client, me, thread["id"], "¿De qué turno es?")

    sent = fake_llm.calls[-1]
    assert [m["role"] for m in sent] == ["user", "assistant", "tool", "assistant", "user"]
    assert sent[0]["content"] == "¿Cuántas secciones hay?"
    assert sent[1]["tool_calls"][0]["function"]["name"] == "datos_del_colegio"
    assert sent[2]["tool_call_id"] == sent[1]["tool_calls"][0]["id"]
    assert sent[-1]["content"] == "¿De qué turno es?"


async def test_the_tool_only_sees_the_directors_school(
    client: httpx.AsyncClient, make_token: MakeToken, fake_llm: FakeLLM
):
    other = bearer(make_token(USER_FLORES, TENANT_B))
    thread = (await client.post("/threads", headers=other)).json()
    fake_llm.script(tool_turn(), text_turn("Una sección."))

    events = await ask(client, other, thread["id"], "¿Qué secciones hay?")

    table = next(e for e in events if e["tipo"] == "tabla")
    assert [row[1] for row in table["filas"]] == ["5to A"]  # San Martín's, never Cristo Rey's


async def test_a_model_failure_becomes_an_error_event_and_is_saved(
    client: httpx.AsyncClient, make_token: MakeToken, fake_llm: FakeLLM
):
    me = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(RuntimeError("the API is down"))

    events = await ask(client, me, thread["id"], "¿Qué secciones hay?")

    assert [e["tipo"] for e in events][-2:] == ["error", "fin"]
    messages = (await client.get(f"/threads/{thread['id']}/messages", headers=me)).json()
    assert messages[-1]["blocks"][0]["codigo"] == "respuesta_fallida"


async def test_asking_in_someone_elses_chat_is_not_found(
    client: httpx.AsyncClient, make_token: MakeToken, fake_llm: FakeLLM
):
    owner = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=owner)).json()
    other = bearer(make_token(USER_FLORES, TENANT_B))
    response = await client.post(
        f"/threads/{thread['id']}/messages", json={"texto": "hola"}, headers=other
    )
    assert response.status_code == 404
    assert fake_llm.calls == []


async def test_tool_arguments_that_are_not_json_answer_as_a_tool_error(
    client: httpx.AsyncClient, make_token: MakeToken, fake_llm: FakeLLM
):
    me = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(arguments="{no es json"), text_turn("No pude consultarlo."))

    events = await ask(client, me, thread["id"], "¿Qué secciones hay?")

    assert not [e for e in events if e["tipo"] == "tabla"]
    sent = fake_llm.calls[-1]
    assert sent[-1]["role"] == "tool"
    assert "not valid JSON" in sent[-1]["content"]


@pytest.mark.parametrize(
    ("tool", "arguments", "status", "block", "in_result"),
    [
        ("resumen_de_niveles", "{}", "Contando los niveles de logro…", "barras_apiladas", "totales"),
        ("alumnos_con_c", "{}", "Buscando alumnos con C…", "tabla", "alumnos_con_C"),
        ("riesgo_por_competencia", "{}", "Buscando rachas de C…", "tabla", "racha_minima"),
        ("proyeccion_de_promocion", '{"grado": "tercero"}', "Proyectando la promoción…", "tabla",
         "es_proyeccion"),
        ("historial_del_alumno", '{"alumno": "Ana Alvarez"}', "Revisando el historial del alumno…",
         "matriz", "cantidad_de_C_por_periodo"),
    ],
)  # fmt: skip
async def test_each_tool_reaches_the_director_and_the_model(
    client: httpx.AsyncClient,
    make_token: MakeToken,
    fake_llm: FakeLLM,
    tool: str,
    arguments: str,
    status: str,
    block: str,
    in_result: str,
):
    me = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(name=tool, arguments=arguments), text_turn("Listo."))

    events = await ask(client, me, thread["id"], "Pregunta de la directora")

    assert status in [e.get("texto") for e in events]
    assert [e["tipo"] for e in events if e["tipo"] not in ("estado", "texto", "fin")] == [block]
    tool_message = fake_llm.calls[-1][-1]
    assert tool_message["role"] == "tool"
    assert in_result in json.loads(tool_message["content"])
    messages = (await client.get(f"/threads/{thread['id']}/messages", headers=me)).json()
    assert [b["tipo"] for b in messages[-1]["blocks"]] == [block, "texto"]


async def test_a_question_to_clarify_reaches_the_model_without_a_block(
    client: httpx.AsyncClient, make_token: MakeToken, fake_llm: FakeLLM
):
    me = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(
        tool_turn(name="historial_del_alumno", arguments='{"alumno": "Huaman"}'),
        text_turn("¿Te refieres a Gabriel Gomez Huaman o a Hilda Huaman Inca?"),
    )

    events = await ask(client, me, thread["id"], "¿Cómo va Huaman?")

    assert not [e for e in events if e["tipo"] in ("tabla", "matriz", "barras_apiladas")]
    result = json.loads(fake_llm.calls[-1][-1]["content"])
    assert result["opciones"] == ["Gabriel Gomez Huaman (3ro A)", "Hilda Huaman Inca (3ro A)"]
