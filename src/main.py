"""Application factory and the `mawta` entrypoint."""

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncGenerator

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

import applog
from chat.llm import LLM
from chat.service import ChatService
from chat.tracing import NoTracer, Tracer
from db import Database
from routes import build_routes
from settings import Settings
from web import Api, RequestLogMiddleware


async def _not_found(_request: Request, _exc: Exception) -> Response:
    return PlainTextResponse("404 page not found\n", status_code=404)


def create_app(
    settings: Settings,
    logger: logging.Logger | None = None,
    chat_llm: LLM | None = None,
    chat_tracer: Tracer | None = None,
) -> Starlette:
    """The whole app: API, worker and director chat. chat_llm replaces the chat's model and
    chat_tracer its tracer (tests)."""
    logger = logger or applog.setup(settings.log_level)
    database = Database(settings.database_url)
    api = Api(db=database, settings=settings, logger=logger)
    chat = ChatService(settings, llm=chat_llm, tracer=chat_tracer or NoTracer())

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncGenerator[None]:
        stack = contextlib.AsyncExitStack()
        await chat.start(stack)
        os.makedirs(settings.storage_dir, exist_ok=True)
        worker_task: asyncio.Task[None] | None = None
        if settings.worker_enabled:
            from worker import run_worker

            worker_task = asyncio.create_task(run_worker(api))
        try:
            yield
        finally:
            await chat.drain()
            if worker_task is not None:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task
            await stack.aclose()
            await database.close()

    app = Starlette(
        routes=build_routes(),
        middleware=[
            Middleware(RequestLogMiddleware, logger=logger, capture=settings.request_body_capture),
            Middleware(
                CORSMiddleware,
                allow_origins=settings.cors_origins,
                allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                allow_headers=["X-Request-ID", "Content-Type"],
                expose_headers=["X-Request-ID"],
                allow_credentials=True,
                max_age=300,
            ),
        ],
        # An unmatched URL answers a plain-text 404. Route handlers
        # render their own 404s as the JSON envelope, so this only sees unknown paths.
        exception_handlers={404: _not_found},
        lifespan=lifespan,
    )
    app.state.api = api
    app.state.chat = chat
    return app


def run() -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue]
    logger = applog.setup(settings.log_level)
    host, port = settings.host_port
    uvicorn.run(
        create_app(settings, logger),
        host=host,
        port=port,
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=5,
    )
