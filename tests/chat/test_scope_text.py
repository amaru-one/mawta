"""A scope tool written as text is answered as if it had been called (official evaluation,
2026-11-16): the director never reads «fuera_de_alcance»."""

import json

import httpx

from chat.llm import ModelTurn
from chat.scope_text import ScopeTextGuard
from chat.tools.scope import OUT_OF_SCOPE
from tests.chat.conftest import ANA, FakeLLM, Session, text_turn
from tests.chat.test_ask import ask
from tests.chat.test_question_bank import bank_row
from tests.conftest import Admin


def run(guard_text: str, chunk: int = 5, tool_calls: list[dict] | None = None):
    shown: list[str] = []
    guard = ScopeTextGuard(shown.append)
    for start in range(0, len(guard_text), chunk):
        guard.feed(guard_text[start : start + chunk])
    message: dict = {"role": "assistant", "content": guard_text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    turn = ModelTurn(message, "stop", "m", 1, 1)
    return guard.finish(turn), "".join(shown)


def test_ordinary_text_streams_through_untouched():
    turn, shown = run("En el Trimestre II hay 20 alumnos con C.")
    assert shown == "En el Trimestre II hay 20 alumnos con C."
    assert turn.message["content"] == shown and "tool_calls" not in turn.message
    turn, shown = run("Fuera de eso, todo bien.")
    assert shown == "Fuera de eso, todo bien."


def test_a_written_out_of_scope_call_becomes_the_tool_call_and_shows_nothing():
    for text in ("fuera_de_alcance", "  `fuera_de_alcance`\n", "fuera_de_alcance {}"):
        turn, shown = run(text)
        assert shown == ""
        assert turn.stop_reason == "tool_calls" and turn.message["content"] is None
        assert turn.message["tool_calls"][0]["function"]["name"] == "fuera_de_alcance"


def test_a_written_no_tool_call_keeps_its_topic():
    turn, shown = run('sin_herramienta {"tema": "tardanzas en marzo"}')
    assert shown == ""
    call = turn.message["tool_calls"][0]["function"]
    assert call["name"] == "sin_herramienta"
    assert json.loads(call["arguments"]) == {"tema": "tardanzas en marzo"}
    turn, _ = run('sin_herramienta(tema="asistencia")')
    assert json.loads(turn.message["tool_calls"][0]["function"]["arguments"]) == {
        "tema": "asistencia"
    }


def test_prose_that_starts_with_a_tool_name_is_shown_in_full():
    turn, shown = run("fuera_de_alcance: no puedo ayudarte con eso.")
    assert shown == "fuera_de_alcance: no puedo ayudarte con eso."
    assert "tool_calls" not in turn.message


def test_a_real_tool_call_wins_over_a_written_one():
    real = [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "datos_del_colegio", "arguments": "{}"},
        }
    ]
    turn, shown = run("fuera_de_alcance", tool_calls=real)
    assert shown == "" and turn.message["tool_calls"] == real and turn.message["content"] is None


async def test_through_the_chat_the_director_gets_the_fixed_phrase(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM, admin: Admin
):
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(text_turn("fuera_de_alcance"))

    events = await ask(client, me, thread["id"], "¿Qué hay de almuerzo?")

    assert "".join(e["delta"] for e in events if e["tipo"] == "texto") == OUT_OF_SCOPE
    assert await bank_row(admin, thread["id"], "¿Qué hay de almuerzo?") == {
        "status": "fuera_de_alcance",
        "tool_name": None,
    }
