"""mawta-chat: the director chat service.

Every route except /health needs `Authorization: Bearer <chat token>`, the
token mawta-server issues at GET /api/v1/auth/chat-token.
"""

import json
import logging
import os
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import BaseModel, Field
from sse_starlette import EventSourceResponse

import repo
from auth import InvalidToken, Principal, TokenVerifier
from db import Database
from graph import SYSTEM_PROMPT, build_graph, thread_key
from llm import LLM, AnthropicLLM
from protocol import event, to_sse
from settings import Settings

log = logging.getLogger("mawta_chat")


class ApiError(Exception):
    status: int
    code: str
    message: str

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class QuestionBody(BaseModel):
    texto: str = Field(min_length=1, max_length=4000)


async def principal(request: Request) -> Principal:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "missing_token", "falta el token del chat")
    try:
        return request.app.state.verifier.verify(token.strip())
    except InvalidToken:
        raise ApiError(401, "invalid_token", "el token del chat no es válido o venció") from None


Director = Annotated[Principal, Depends(principal)]


def create_app(settings: Settings | None = None, llm: LLM | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # Settings reads its required fields from the environment, which the
        # checker cannot see.
        cfg = settings or Settings()  # pyright: ignore[reportCallIssue]
        model = llm or AnthropicLLM(
            api_key=cfg.anthropic_api_key.get_secret_value(),
            model=cfg.chat_model,
            effort=cfg.chat_effort,
            max_tokens=cfg.chat_max_tokens,
        )
        app.state.verifier = TokenVerifier(cfg.chat_token_public_keys)
        app.state.db = Database(cfg.chat_database_url)
        await app.state.db.open()
        try:
            async with AsyncPostgresSaver.from_conn_string(cfg.langgraph_database_url) as saver:
                await saver.setup()
                app.state.saver = saver
                app.state.graph = build_graph(model, cfg.chat_max_model_calls, saver)
                yield
        finally:
            await app.state.db.close()

    app = FastAPI(title="mawta-chat", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            status_code=exc.status,
        )

    def not_found() -> ApiError:
        return ApiError(404, "thread_not_found", "no encontramos ese chat")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/threads")
    async def list_threads(request: Request, who: Director) -> list[dict[str, Any]]:
        async with request.app.state.db.tenant_tx(who) as conn:
            return await repo.list_threads(conn)

    @app.post("/threads", status_code=201)
    async def create_thread(request: Request, who: Director) -> dict[str, Any]:
        async with request.app.state.db.tenant_tx(who) as conn:
            return await repo.create_thread(conn, who)

    @app.patch("/threads/{thread_id}")
    async def rename_thread(
        thread_id: UUID,
        body: RenameBody,
        request: Request,
        who: Director,
    ) -> dict[str, Any]:
        async with request.app.state.db.tenant_tx(who) as conn:
            thread = await repo.rename_thread(conn, thread_id, body.title.strip())
        if thread is None:
            raise not_found()
        return thread

    @app.delete("/threads/{thread_id}", status_code=204)
    async def delete_thread(thread_id: UUID, request: Request, who: Director) -> Response:
        async with request.app.state.db.tenant_tx(who) as conn:
            deleted = await repo.delete_thread(conn, thread_id)
        if not deleted:
            raise not_found()
        await request.app.state.saver.adelete_thread(
            thread_key(who.tenant_id, who.user_id, thread_id)
        )
        return Response(status_code=204)

    @app.get("/threads/{thread_id}/messages")
    async def list_messages(
        thread_id: UUID, request: Request, who: Director
    ) -> list[dict[str, Any]]:
        async with request.app.state.db.tenant_tx(who) as conn:
            if await repo.get_thread(conn, thread_id) is None:
                raise not_found()
            return await repo.list_messages(conn, thread_id)

    @app.post("/threads/{thread_id}/messages")
    async def ask(
        thread_id: UUID,
        body: QuestionBody,
        request: Request,
        who: Director,
    ) -> EventSourceResponse:
        question = body.texto.strip()
        if not question:
            raise ApiError(422, "empty_question", "escribe una pregunta")
        db: Database = request.app.state.db
        async with db.tenant_tx(who) as conn:
            if await repo.get_thread(conn, thread_id) is None:
                raise not_found()
            await repo.add_director_message(conn, who, thread_id, question)
            school = await repo.school_name(conn)
        return EventSourceResponse(answer(request.app, who, thread_id, question, school))

    async def answer(
        app: FastAPI, who: Principal, thread_id: UUID, question: str, school: str
    ) -> AsyncIterator[dict[str, str]]:
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
                "thread_id": thread_key(who.tenant_id, who.user_id, thread_id),
                "system": SYSTEM_PROMPT.format(school=school),
                "db": app.state.db,
                "principal": who,
            }
        }
        graph_input = {
            "messages": [{"role": "user", "content": question}],
            "model_calls": 0,
            "stop_reason": None,
        }
        try:
            async for chunk in app.state.graph.astream(graph_input, config, stream_mode="custom"):
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
                        event(
                            shown["tipo"],
                            **{k: v for k, v in shown.items() if k != "tipo"},
                        )
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

        async with app.state.db.tenant_tx(who) as conn:
            message_id = await repo.add_mawta_message(
                conn,
                who,
                thread_id,
                blocks,
                json.loads(json.dumps(tool_calls, default=str)),
                usage_model,
                input_tokens,
                output_tokens,
                int((time.monotonic() - started) * 1000),
            )
        yield to_sse(event("fin", message_id=str(message_id)))

    return app


def run() -> None:
    """Run the service with uvicorn (`uv run mawta-chat`)."""
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run(create_app(), host=host, port=port)
