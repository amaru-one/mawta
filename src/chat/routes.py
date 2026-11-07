"""The director chat's HTTP routes, under /api/v1/chat. Every route but /health needs a director's
session (the same cookie as the rest of the app); the chat's own work runs in Database.chat_tx,
as mawta_chat.

Asking streams Server-Sent Events in protocol v1 (chat/protocol.py) and saves the answer when it
ends.
"""

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sse_starlette import EventSourceResponse
from starlette.requests import Request
from starlette.responses import Response

from chat import repo
from chat.graph import SYSTEM_PROMPT, thread_key
from chat.protocol import event, to_sse
from chat.service import ChatService
from db import Database, RequestCtx
from errors import AppError
from web import api_of, ctx_of, no_content, path_uuid, read_json, write_json

log = logging.getLogger("mawta.chat")

TITLE_MAX = 200
QUESTION_MAX = 4000


def chat_of(request: Request) -> ChatService:
    return request.app.state.chat


def _director(request: Request) -> tuple[Database, RequestCtx, UUID]:
    ctx = ctx_of(request)
    assert ctx.actor_id is not None
    return api_of(request).db, ctx, ctx.actor_id


def _not_found() -> AppError:
    return AppError(404, "thread_not_found", "no encontramos ese chat")


def _text(body: dict[str, Any], name: str, max_len: int) -> str:
    """A required text field between 1 and max_len characters."""
    value = body.get(name)
    if not isinstance(value, str) or not 1 <= len(value) <= max_len:
        raise AppError(
            422, "validation_error", f"{name} debe ser un texto de 1 a {max_len} caracteres"
        )
    return value


async def handle_health(_request: Request) -> Response:
    return write_json({"status": "ok"})


async def handle_list_threads(request: Request) -> Response:
    db, ctx, user = _director(request)
    async with db.chat_tx(ctx) as conn:
        return write_json(await repo.list_threads(conn, user))


async def handle_create_thread(request: Request) -> Response:
    db, ctx, user = _director(request)
    async with db.chat_tx(ctx) as conn:
        return write_json(await repo.create_thread(conn, user), 201)


async def handle_rename_thread(request: Request) -> Response:
    db, ctx, user = _director(request)
    thread_id = path_uuid(request, "threadID")
    title = _text(await read_json(request), "title", TITLE_MAX).strip()
    async with db.chat_tx(ctx) as conn:
        thread = await repo.rename_thread(conn, user, thread_id, title)
    if thread is None:
        raise _not_found()
    return write_json(thread)


async def handle_delete_thread(request: Request) -> Response:
    db, ctx, user = _director(request)
    thread_id = path_uuid(request, "threadID")
    async with db.chat_tx(ctx) as conn:
        deleted = await repo.delete_thread(conn, user, thread_id)
    if not deleted:
        raise _not_found()
    chat = chat_of(request)
    if chat.saver is not None:
        await chat.saver.adelete_thread(thread_key(user, thread_id))
    return no_content()


async def handle_list_messages(request: Request) -> Response:
    db, ctx, user = _director(request)
    thread_id = path_uuid(request, "threadID")
    async with db.chat_tx(ctx) as conn:
        if await repo.get_thread(conn, user, thread_id) is None:
            raise _not_found()
        return write_json(await repo.list_messages(conn, user, thread_id))


async def handle_ask(request: Request) -> Response:
    db, ctx, user = _director(request)
    thread_id = path_uuid(request, "threadID")
    question = _text(await read_json(request), "texto", QUESTION_MAX).strip()
    if not question:
        raise AppError(422, "empty_question", "escribe una pregunta")
    chat = chat_of(request)
    chat.take_slot()
    try:
        async with db.chat_tx(ctx) as conn:
            if await repo.get_thread(conn, user, thread_id) is None:
                raise _not_found()
            await repo.add_director_message(conn, user, thread_id, question)
            school = await repo.school_name(conn)
    except BaseException:
        chat.release_slot()
        raise
    return EventSourceResponse(_answer(chat, db, ctx, thread_id, question, school))


async def _answer(
    chat: ChatService, db: Database, ctx: RequestCtx, thread_id: UUID, question: str, school: str
) -> AsyncIterator[dict[str, str]]:
    """Stream one answer and save it. Holds an answering slot until it ends, however it ends."""
    assert ctx.actor_id is not None
    try:
        started = time.monotonic()
        blocks: list[dict[str, Any]] = []
        text: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        usage_model: str | None = None
        input_tokens = output_tokens = 0

        def flush_text() -> None:
            if "".join(text).strip():
                blocks.append({"tipo": "texto", "md": "".join(text)})
            text.clear()

        yield to_sse(event("estado", texto="Pensando…"))
        config = {
            "configurable": {
                "thread_id": thread_key(ctx.actor_id, thread_id),
                "system": SYSTEM_PROMPT.format(school=school),
                "db": db,
                "ctx": ctx,
            }
        }
        graph_input = {
            "messages": [{"role": "user", "content": question}],
            "model_calls": 0,
            "stop_reason": None,
        }
        try:
            async for chunk in chat.graph.astream(graph_input, config, stream_mode="custom"):
                kind = chunk["kind"]
                if kind == "text":
                    text.append(chunk["delta"])
                    yield to_sse(event("texto", delta=chunk["delta"]))
                elif kind == "status":
                    yield to_sse(event("estado", texto=chunk["texto"]))
                elif kind == "block":
                    flush_text()
                    shown = chunk["block"]
                    blocks.append(shown)
                    yield to_sse(
                        event(shown["tipo"], **{k: v for k, v in shown.items() if k != "tipo"})
                    )
                elif kind == "tool_call":
                    tool_calls.append({k: v for k, v in chunk.items() if k != "kind"})
                elif kind == "usage":
                    usage_model = chunk["model"]
                    input_tokens += chunk["input_tokens"]
                    output_tokens += chunk["output_tokens"]
                elif kind == "error":
                    flush_text()
                    failure = {
                        "tipo": "error",
                        "codigo": chunk["codigo"],
                        "mensaje": chunk["mensaje"],
                    }
                    blocks.append(failure)
                    yield to_sse(event("error", codigo=chunk["codigo"], mensaje=chunk["mensaje"]))
        except Exception:
            log.exception("answering thread %s failed", thread_id)
            flush_text()
            failure = {
                "tipo": "error",
                "codigo": "respuesta_fallida",
                "mensaje": "No pudimos responder ahora. Inténtalo de nuevo en unos segundos.",
            }
            blocks.append(failure)
            yield to_sse(event("error", codigo=failure["codigo"], mensaje=failure["mensaje"]))
        flush_text()

        async with db.chat_tx(ctx) as conn:
            message_id = await repo.add_mawta_message(
                conn,
                ctx.actor_id,
                thread_id,
                blocks,
                json.loads(json.dumps(tool_calls, default=str)),
                usage_model,
                input_tokens,
                output_tokens,
                int((time.monotonic() - started) * 1000),
            )
        yield to_sse(event("fin", message_id=str(message_id)))
    finally:
        chat.release_slot()
