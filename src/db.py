"""The database engine and the transactions every query goes through.

Each helper yields a SQLAlchemy AsyncConnection inside one transaction (psycopg 3 underneath).
Everything is set with `set_config(..., true)`, the SET LOCAL form, so the role and the session
values evaporate at commit or rollback and pooled connections never leak one request's identity
into the next. Repo code only ever receives a connection from one of these helpers.

The roles:

- mawta_app: every request and job of the application. Not the owner of any table.
- mawta_chat: the director chat. It reads only the chat_api views and writes only schema chat,
  where row-level security (owner_only) keeps each director's chats to themselves. The model's
  tools run here, so whatever SQL the model triggers cannot reach the tables of public.
"""

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Executable, RowMapping, create_engine, func, pool, select, true
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

import jsonutil

# The chat's limits. They used to be the mawta_chat role's own settings (ALTER ROLE ... SET),
# but those apply only when logging in as the role, never after SET ROLE, so each chat
# transaction sets them itself.
CHAT_LIMITS = {
    "statement_timeout": "15s",
    "lock_timeout": "2s",
    "idle_in_transaction_session_timeout": "30s",
}


def sa_url(url: str) -> str:
    """A postgres:// or postgresql:// URL, in the form SQLAlchemy's psycopg driver expects."""
    return re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+psycopg://", url)


@dataclass(frozen=True)
class RequestCtx:
    """Who is acting, for one request or job."""

    actor_id: UUID | None = None  # None when acting as the system (a job without a user)
    teacher_id: UUID | None = None
    request_id: str = ""
    role: str = ""  # the acting user_sessions.role; empty for a system actor

    def with_teacher(self, teacher_id: UUID) -> "RequestCtx":
        return replace(self, teacher_id=teacher_id)


def engine_for(url: str, pool_size: int = 5, max_overflow: int = 5) -> AsyncEngine:
    return create_async_engine(
        sa_url(url),
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        # jsonb columns encode UUIDs, dates and decimals the way the API responses do.
        json_serializer=jsonutil.dumps_str,
    )


def admin_engine(url: str) -> Engine:
    """A synchronous engine for the command-line tools (onboard, useradd), which run as the
    database owner and open one connection."""
    return create_engine(sa_url(url), poolclass=pool.NullPool, json_serializer=jsonutil.dumps_str)


async def _set(conn: AsyncConnection, values: dict[str, str]) -> None:
    """SET LOCAL for several settings in one round trip."""
    await conn.execute(select(*(func.set_config(k, v, true()) for k, v in values.items())))


class Database:
    engine: AsyncEngine

    def __init__(self, url: str, pool_size: int = 5, max_overflow: int = 5) -> None:
        self.engine = engine_for(url, pool_size, max_overflow)

    async def close(self) -> None:
        await self.engine.dispose()

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(select(1))

    @asynccontextmanager
    async def user_tx(self, ctx: RequestCtx) -> AsyncIterator[AsyncConnection]:
        """A transaction as mawta_app, with the actor and request id the schema reads back
        (app.current_actor_id(), app.log_event)."""
        async with self.engine.begin() as conn:
            await _set(
                conn,
                {
                    "role": "mawta_app",
                    "app.actor_id": str(ctx.actor_id) if ctx.actor_id else "",
                    "app.request_id": ctx.request_id,
                },
            )
            yield conn

    @asynccontextmanager
    async def auth_tx(self, request_id: str = "") -> AsyncIterator[AsyncConnection]:
        """A transaction as mawta_app before anyone is known: login and session checks."""
        async with self.engine.begin() as conn:
            await _set(conn, {"role": "mawta_app", "app.request_id": request_id})
            yield conn

    @asynccontextmanager
    async def chat_tx(self, ctx: RequestCtx) -> AsyncIterator[AsyncConnection]:
        """A transaction as mawta_chat for the director chat: its threads and messages, and the
        model's tools over chat_api. app.actor_id is what owner_only checks."""
        if ctx.actor_id is None:
            raise ValueError("the chat always acts for a director")
        async with self.engine.begin() as conn:
            await _set(
                conn,
                {"role": "mawta_chat", "app.actor_id": str(ctx.actor_id), **CHAT_LIMITS},
            )
            yield conn

    @asynccontextmanager
    async def system_tx(self) -> AsyncIterator[AsyncConnection]:
        """A transaction as the engine's own login role, with no actor.

        For the job queue (jobs has no row security) and for the system's own work. Never
        for request data: use user_tx.
        """
        async with self.engine.begin() as conn:
            yield conn


def returned(row: RowMapping | None) -> RowMapping:
    """The row of a statement that always yields one (insert ... returning, an aggregate).
    None here is a bug, not a lookup that matched nothing (that is fetch_required)."""
    if row is None:
        raise RuntimeError("the statement returned no row")
    return row


async def fetch_one(conn: AsyncConnection, stmt: Executable) -> RowMapping | None:
    return (await conn.execute(stmt)).mappings().first()


async def fetch_all(conn: AsyncConnection, stmt: Executable) -> list[RowMapping]:
    return list((await conn.execute(stmt)).mappings().all())


async def fetch_required(conn: AsyncConnection, stmt: Executable) -> RowMapping:
    """fetch_one, but no row raises NotFound (a lookup that matched nothing)."""
    from errors import NotFound

    row = await fetch_one(conn, stmt)
    if row is None:
        raise NotFound
    return row


async def scalar(conn: AsyncConnection, stmt: Executable) -> Any:
    """The single value of a statement that returns one row and one column."""
    return (await conn.execute(stmt)).scalar_one()
