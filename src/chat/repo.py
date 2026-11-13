"""Queries on the chat schema. Every function takes a connection opened by Database.chat_tx and
the director acting.

Each director's chats are private twice over: every query filters by the director's user_id, and
row-level security (owner_only, on app.actor_id) refuses any other row even if a query forgot to.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import case, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_one, scalar
from mawta_schema import api_views as v
from mawta_schema.tables import ChatMessage, ChatQuestionBank, ChatThread

DEFAULT_TITLE = "Nuevo chat"
TITLE_MAX = 60

T, M = ChatThread, ChatMessage
_THREAD = (T.id, T.title, T.created_at, T.updated_at)


def _mine(user_id: UUID, thread_id: UUID | None = None) -> list[Any]:
    where = [T.user_id == user_id, T.deleted_at.is_(None)]
    if thread_id is not None:
        where.append(T.id == thread_id)
    return where


async def list_threads(conn: AsyncConnection, user_id: UUID) -> list[dict[str, Any]]:
    rows = await conn.execute(select(*_THREAD).where(*_mine(user_id)).order_by(T.updated_at.desc()))
    return [dict(r) for r in rows.mappings()]


async def create_thread(conn: AsyncConnection, user_id: UUID) -> dict[str, Any]:
    row = await fetch_one(conn, insert(T).values(user_id=user_id).returning(*_THREAD))
    assert row is not None
    return dict(row)


async def get_thread(
    conn: AsyncConnection, user_id: UUID, thread_id: UUID
) -> dict[str, Any] | None:
    row = await fetch_one(conn, select(*_THREAD).where(*_mine(user_id, thread_id)))
    return dict(row) if row else None


async def rename_thread(
    conn: AsyncConnection, user_id: UUID, thread_id: UUID, title: str
) -> dict[str, Any] | None:
    row = await fetch_one(
        conn,
        update(T).where(*_mine(user_id, thread_id)).values(title=title).returning(*_THREAD),
    )
    return dict(row) if row else None


async def delete_thread(conn: AsyncConnection, user_id: UUID, thread_id: UUID) -> bool:
    result = await conn.execute(
        update(T).where(*_mine(user_id, thread_id)).values(deleted_at=func.now())
    )
    return result.rowcount == 1


async def list_messages(
    conn: AsyncConnection, user_id: UUID, thread_id: UUID
) -> list[dict[str, Any]]:
    rows = await conn.execute(
        select(M.id, M.author, M.protocol_version, M.blocks, M.created_at)
        .where(M.thread_id == thread_id, M.user_id == user_id)
        .order_by(M.created_at, M.id)
    )
    return [dict(r) for r in rows.mappings()]


async def add_director_message(
    conn: AsyncConnection, user_id: UUID, thread_id: UUID, text: str
) -> UUID:
    message_id = await scalar(
        conn,
        insert(M)
        .values(
            thread_id=thread_id,
            user_id=user_id,
            author="director",
            blocks=[{"tipo": "texto", "md": text}],
        )
        .returning(M.id),
    )
    # The first question names the chat, unless the director already did.
    title = text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1].rstrip() + "…"
    await conn.execute(
        update(T)
        .where(*_mine(user_id, thread_id))
        .values(
            title=case((T.title == DEFAULT_TITLE, title), else_=T.title),
            updated_at=func.now(),
        )
    )
    return message_id


async def add_mawta_message(
    conn: AsyncConnection,
    user_id: UUID,
    thread_id: UUID,
    blocks: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
) -> UUID:
    message_id = await scalar(
        conn,
        insert(M)
        .values(
            thread_id=thread_id,
            user_id=user_id,
            author="mawta",
            blocks=blocks,
            tool_calls=tool_calls,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
        .returning(M.id),
    )
    await conn.execute(update(T).where(*_mine(user_id, thread_id)).values(updated_at=func.now()))
    return message_id


async def add_question(
    conn: AsyncConnection, message_id: UUID, question: str, status: str, tool_name: str | None
) -> None:
    """One row of the question bank per question: how it ended, and which tool answered or was
    missing (D017). message_id is the director's message."""
    await conn.execute(
        insert(ChatQuestionBank).values(
            message_id=message_id, question=question, status=status, tool_name=tool_name
        )
    )


async def school_name(conn: AsyncConnection) -> str:
    row = await fetch_one(conn, select(v.school.c.name))
    return row["name"] if row else "el colegio"
