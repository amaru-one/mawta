"""The answer is never lost (roadmap level 1, item 7): it is built and saved by its own task, so a
director who closes the browser mid-stream finds the whole answer when the chat reopens, and the
answering slot is released once it is saved."""

import asyncio
from typing import Any, cast

import httpx
from starlette.applications import Starlette

from chat import routes
from chat.llm import ModelTurn
from chat.service import ChatService
from db import Database, RequestCtx
from tests.chat.conftest import ANA, FakeLLM, Session, text_turn, tool_turn
from tests.conftest import Databases


class SlowLLM(FakeLLM):
    """Each turn waits until the test lets it go, so the stream can be abandoned mid-answer."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    async def respond(self, *args: Any, **kwargs: Any) -> ModelTurn:
        await self.gate.wait()
        return await super().respond(*args, **kwargs)


def app_of(client: httpx.AsyncClient) -> Starlette:
    return cast(Any, client._transport).app  # pyright: ignore[reportPrivateUsage]


async def test_an_abandoned_stream_still_saves_the_whole_answer(
    chat_client_for: Any, session: Session, databases: Databases
):
    llm = SlowLLM()
    client: httpx.AsyncClient = await chat_client_for(llm)
    chat: ChatService = app_of(client).state.chat
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    llm.script(tool_turn(), text_turn("Tres secciones: 2do A, 3ro A y 5to B."))

    # The director asks and leaves before any event arrives: nobody reads the stream.
    db = Database(databases.app_url, pool_size=1)
    ctx = RequestCtx(actor_id=ANA, role="director")
    async with db.chat_tx(ctx) as conn:
        from chat import repo

        question_id = await repo.add_director_message(
            conn, ANA, thread["id"], "¿Qué secciones tiene mi colegio?"
        )
    chat.take_slot()
    events = routes.start_answer(
        chat, db, ctx, thread["id"], question_id, "¿Qué secciones tiene mi colegio?", "Cristo Rey"
    )
    assert chat.answering == 1 and len(chat.tasks) == 1
    llm.gate.set()
    await asyncio.gather(*chat.tasks)

    assert chat.answering == 0, "the slot is released once the answer is saved"
    messages = (await client.get(f"/threads/{thread['id']}/messages", headers=me)).json()
    assert [m["author"] for m in messages] == ["director", "mawta"]
    assert [b["tipo"] for b in messages[1]["blocks"]] == ["tabla", "texto"]
    assert messages[1]["blocks"][1]["md"] == "Tres secciones: 2do A, 3ro A y 5to B."
    # The events were produced anyway, ending with `fin` and the close marker.
    produced: list[dict[str, str] | None] = []
    while not events.empty():
        produced.append(events.get_nowait())
    assert produced[-1] is None and produced[-2] is not None
    assert produced[-2]["event"] == "fin"
    await db.close()


async def test_the_stream_still_delivers_every_event_in_order(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM
):
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(), text_turn("Listo."))

    response = await client.post(
        f"/threads/{thread['id']}/messages", json={"texto": "¿Secciones?"}, headers=me
    )

    kinds = [line.split()[1] for line in response.text.splitlines() if line.startswith("event:")]
    assert kinds[0] == "estado" and kinds[-1] == "fin"
    assert "tabla" in kinds and "texto" in kinds
    chat: ChatService = app_of(client).state.chat
    await asyncio.gather(*chat.tasks)
    assert chat.answering == 0 and not chat.tasks
