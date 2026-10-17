"""A question streams protocol v1 events and both messages are saved."""

import json
from typing import Any

from conftest import TENANT_A, TENANT_B, USER_FLORES, USER_QUISPE, bearer, text_turn, tool_turn


def parse_sse(body: str) -> list[dict[str, Any]]:
    events = []
    for chunk in body.replace("\r\n", "\n").split("\n\n"):
        data = [
            line[len("data:") :].strip() for line in chunk.split("\n") if line.startswith("data:")
        ]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


async def ask(client, headers, thread_id, text) -> list[dict[str, Any]]:
    response = await client.post(
        f"/threads/{thread_id}/messages", json={"texto": text}, headers=headers
    )
    assert response.status_code == 200, response.text
    return parse_sse(response.text)


async def test_a_question_uses_the_tool_and_streams_the_answer(client, make_token, fake_llm):
    me = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(), text_turn("Tu colegio tiene una sección: 5to B."))

    events = await ask(client, me, thread["id"], "¿Qué secciones tiene mi colegio?")

    assert all(e["version"] == 1 for e in events)
    kinds = [e["tipo"] for e in events]
    assert kinds[0] == "estado" and kinds[-1] == "fin"
    assert "Consultando las secciones del colegio…" in [e.get("texto") for e in events]
    table = next(e for e in events if e["tipo"] == "tabla")
    assert table["filas"] == [[2026, "Quinto de secundaria", "B", "Mañana", "Activa"]]
    answer = "".join(e["delta"] for e in events if e["tipo"] == "texto")
    assert answer == "Tu colegio tiene una sección: 5to B."
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


async def test_the_next_question_carries_the_history(client, make_token, fake_llm):
    me = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(), text_turn("Una sección."), text_turn("Es de turno mañana."))

    await ask(client, me, thread["id"], "¿Cuántas secciones hay?")
    await ask(client, me, thread["id"], "¿De qué turno es?")

    sent = fake_llm.calls[-1]
    assert [m["role"] for m in sent] == ["user", "assistant", "user", "assistant", "user"]
    assert sent[0]["content"] == "¿Cuántas secciones hay?"
    assert sent[1]["content"][0]["type"] == "tool_use"
    assert sent[2]["content"][0]["type"] == "tool_result"
    assert sent[-1]["content"] == "¿De qué turno es?"


async def test_the_tool_only_sees_the_directors_school(client, make_token, fake_llm):
    other = bearer(make_token(USER_FLORES, TENANT_B))
    thread = (await client.post("/threads", headers=other)).json()
    fake_llm.script(tool_turn(), text_turn("Una sección."))

    events = await ask(client, other, thread["id"], "¿Qué secciones hay?")

    table = next(e for e in events if e["tipo"] == "tabla")
    assert [row[2] for row in table["filas"]] == [
        "A"
    ]  # San Martín's 5to A, never Cristo Rey's 5to B


async def test_a_model_failure_becomes_an_error_event_and_is_saved(client, make_token, fake_llm):
    me = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(RuntimeError("the API is down"))

    events = await ask(client, me, thread["id"], "¿Qué secciones hay?")

    assert [e["tipo"] for e in events][-2:] == ["error", "fin"]
    messages = (await client.get(f"/threads/{thread['id']}/messages", headers=me)).json()
    assert messages[-1]["blocks"][0]["codigo"] == "respuesta_fallida"


async def test_asking_in_someone_elses_chat_is_not_found(client, make_token, fake_llm):
    owner = bearer(make_token(USER_QUISPE, TENANT_A))
    thread = (await client.post("/threads", headers=owner)).json()
    other = bearer(make_token(USER_FLORES, TENANT_B))
    response = await client.post(
        f"/threads/{thread['id']}/messages", json={"texto": "hola"}, headers=other
    )
    assert response.status_code == 404
    assert fake_llm.calls == []
