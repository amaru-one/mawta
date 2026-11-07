"""What keeps the chat inside its limits: who may use it, what its database role may read, how
long its transactions may run, whose chats it sees, how many questions it answers at once, and
what happens without a model."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from chat.llm import ModelTurn
from db import Database, RequestCtx
from mawta_schema.tables import ChatThread
from tests.chat.conftest import ANA, BETO, QUISPE, FakeLLM, Session, text_turn, tool_turn
from tests.conftest import Databases

ChatClientFor = Callable[..., Awaitable[httpx.AsyncClient]]

ROUTES = [
    ("GET", "/threads"),
    ("POST", "/threads"),
    ("PATCH", "/threads/00000000-0000-0000-0000-000000000001"),
    ("DELETE", "/threads/00000000-0000-0000-0000-000000000001"),
    ("GET", "/threads/00000000-0000-0000-0000-000000000001/messages"),
    ("POST", "/threads/00000000-0000-0000-0000-000000000001/messages"),
]


def events(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith("data:")]


@pytest.fixture
def database(databases: Databases) -> Database:
    return Database(databases.app_url, pool_size=1)


async def test_a_teacher_cannot_use_the_chat(client: httpx.AsyncClient, session: Session):
    teacher = await session(QUISPE, "teacher")
    for method, path in ROUTES:
        body = {"title": "x", "texto": "hola"}
        response = await client.request(method, path, json=body, headers=teacher)
        assert response.status_code == 403, (method, path)
        assert response.json()["error"]["code"] == "not_a_director"
        assert (await client.request(method, path, json=body)).status_code == 401, (method, path)
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_the_chat_cannot_read_school_tables(database: Database):
    async with database.chat_tx(RequestCtx(actor_id=ANA)) as conn:
        assert await conn.scalar(text("select count(*) from chat_api.students")) is not None
    with pytest.raises(DBAPIError, match="permission denied"):
        async with database.chat_tx(RequestCtx(actor_id=ANA)) as conn:
            await conn.execute(text("select count(*) from public.students"))
    await database.close()


async def test_chat_transactions_have_their_limits(database: Database):
    async with database.chat_tx(RequestCtx(actor_id=ANA)) as conn:
        assert await conn.scalar(text("show statement_timeout")) == "15s"
        assert await conn.scalar(text("show lock_timeout")) == "2s"
        assert await conn.scalar(text("show idle_in_transaction_session_timeout")) == "30s"
        assert await conn.scalar(select(func.current_user())) == "mawta_chat"
    # Nothing leaks into the next transaction on the same pooled connection.
    async with database.user_tx(RequestCtx(actor_id=ANA)) as conn:
        assert await conn.scalar(text("show statement_timeout")) == "0"
        assert await conn.scalar(select(func.current_user())) == "mawta_app"
    await database.close()


async def test_owner_only_at_the_database(
    database: Database, client: httpx.AsyncClient, session: Session
):
    thread = (await client.post("/threads", headers=await session(ANA))).json()["id"]
    async with database.chat_tx(RequestCtx(actor_id=BETO)) as conn:
        seen = (await conn.execute(select(ChatThread.id))).scalars().all()
        assert thread not in {str(t) for t in seen}
        renamed = await conn.execute(
            update(ChatThread).where(ChatThread.id == thread).values(title="ajeno")
        )
        assert renamed.rowcount == 0
    with pytest.raises(DBAPIError, match="row-level security"):
        async with database.chat_tx(RequestCtx(actor_id=BETO)) as conn:
            await conn.execute(insert(ChatThread).values(user_id=ANA))
    await database.close()


class GatedLLM(FakeLLM):
    """A fake model whose answers wait until the test opens the gate."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    async def respond(self, system, messages, tools, on_text, /) -> ModelTurn:  # type: ignore[override]
        self.calls.append([dict(m) for m in messages])
        await self.gate.wait()
        turn = self.turns.pop(0)
        assert isinstance(turn, ModelTurn)
        return turn


async def test_too_many_questions_at_once_are_refused(
    chat_client_for: ChatClientFor, session: Session
):
    llm = GatedLLM()
    llm.script(text_turn("uno"), text_turn("tres"))
    client = await chat_client_for(llm, chat_max_concurrent=1)
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()["id"]

    first = asyncio.create_task(
        client.post(f"/threads/{thread}/messages", json={"texto": "uno"}, headers=me)
    )
    for _ in range(100):
        if llm.calls:
            break
        await asyncio.sleep(0.02)
    second = await client.post(f"/threads/{thread}/messages", json={"texto": "dos"}, headers=me)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "chat_busy"

    llm.gate.set()
    assert events((await first).text)[-1]["tipo"] == "fin"
    third = await client.post(f"/threads/{thread}/messages", json={"texto": "tres"}, headers=me)
    assert third.status_code == 200 and events(third.text)[-1]["tipo"] == "fin"


async def test_no_chat_model_means_chat_unavailable(
    chat_client_for: ChatClientFor, session: Session
):
    client = await chat_client_for(None, chat_model="", langgraph_database_url="")
    me = await session(ANA)
    assert (await client.get("/threads", headers=me)).status_code == 200
    thread = (await client.post("/threads", headers=me)).json()["id"]
    asked = await client.post(f"/threads/{thread}/messages", json={"texto": "hola"}, headers=me)
    assert asked.status_code == 503
    assert asked.json()["error"]["code"] == "chat_unavailable"
    assert (await client.delete(f"/threads/{thread}", headers=me)).status_code == 204


async def test_an_openrouter_model_without_its_key_is_unavailable(
    chat_client_for: ChatClientFor, session: Session
):
    client = await chat_client_for(None, chat_model="openrouter:qwen/qwen3")
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()["id"]
    asked = await client.post(f"/threads/{thread}/messages", json={"texto": "hola"}, headers=me)
    assert asked.status_code == 503
    assert asked.json()["error"]["code"] == "chat_unavailable"


async def test_a_question_is_remembered(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM, databases: Databases
):
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()["id"]
    fake_llm.script(tool_turn(), text_turn("Tres secciones."), text_turn("Turno mañana."))
    for question in ("¿Cuántas secciones hay?", "¿De qué turno?"):
        response = await client.post(
            f"/threads/{thread}/messages", json={"texto": question}, headers=me
        )
        assert events(response.text)[-1]["tipo"] == "fin"

    roles = [m["role"] for m in fake_llm.calls[-1]]
    assert roles == ["user", "assistant", "tool", "assistant", "user"]

    database = Database(databases.admin_url, pool_size=1)
    count = text("select count(*) from langgraph.checkpoints where thread_id = :key")
    async with database.system_tx() as conn:
        assert await conn.scalar(count, {"key": f"{ANA}:{thread}"}) > 0
    assert (await client.delete(f"/threads/{thread}", headers=me)).status_code == 204
    async with database.system_tx() as conn:
        assert await conn.scalar(count, {"key": f"{ANA}:{thread}"}) == 0
    await database.close()


async def test_bad_bodies_and_ids_are_rejected(client: httpx.AsyncClient, session: Session):
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()["id"]
    for body, code in (({"texto": "   "}, "empty_question"), ({}, "validation_error")):
        response = await client.post(f"/threads/{thread}/messages", json=body, headers=me)
        assert (response.status_code, response.json()["error"]["code"]) == (422, code)
    long_title = {"title": "x" * 201}
    response = await client.patch(f"/threads/{thread}", json=long_title, headers=me)
    assert (response.status_code, response.json()["error"]["code"]) == (422, "validation_error")
    assert (await client.get("/threads/not-a-uuid/messages", headers=me)).status_code == 400
