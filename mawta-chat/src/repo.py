"""Queries on the chat schema. Every function takes a connection opened by
Database.tenant_tx, so RLS limits it to the director's own school and chats."""

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection, AsyncCursor
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from auth import Principal

DEFAULT_TITLE = "Nuevo chat"
TITLE_MAX = 60


async def returned(cur: AsyncCursor[DictRow]) -> DictRow:
    """The row of an insert ... returning, which always has one."""
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("the statement returned no row")
    return row


async def list_threads(conn: AsyncConnection[DictRow]) -> list[dict[str, Any]]:
    cur = await conn.execute(
        """
        select id, title, created_at, updated_at
          from chat.threads
         where deleted_at is null
         order by updated_at desc
        """
    )
    return await cur.fetchall()


async def create_thread(conn: AsyncConnection[DictRow], principal: Principal) -> dict[str, Any]:
    cur = await conn.execute(
        """
        insert into chat.threads (tenant_id, user_id)
        values (%s, %s)
        returning id, title, created_at, updated_at
        """,
        (principal.tenant_id, principal.user_id),
    )
    return await returned(cur)


async def get_thread(conn: AsyncConnection[DictRow], thread_id: UUID) -> dict[str, Any] | None:
    cur = await conn.execute(
        "select id, title, created_at, updated_at from chat.threads where id = %s and deleted_at is null",
        (thread_id,),
    )
    return await cur.fetchone()


async def rename_thread(
    conn: AsyncConnection[DictRow], thread_id: UUID, title: str
) -> dict[str, Any] | None:
    cur = await conn.execute(
        """
        update chat.threads set title = %s
         where id = %s and deleted_at is null
        returning id, title, created_at, updated_at
        """,
        (title, thread_id),
    )
    return await cur.fetchone()


async def delete_thread(conn: AsyncConnection[DictRow], thread_id: UUID) -> bool:
    cur = await conn.execute(
        "update chat.threads set deleted_at = now() where id = %s and deleted_at is null",
        (thread_id,),
    )
    return cur.rowcount == 1


async def list_messages(conn: AsyncConnection[DictRow], thread_id: UUID) -> list[dict[str, Any]]:
    cur = await conn.execute(
        """
        select id, author, protocol_version, blocks, created_at
          from chat.messages
         where thread_id = %s
         order by created_at, id
        """,
        (thread_id,),
    )
    return await cur.fetchall()


async def add_director_message(
    conn: AsyncConnection[DictRow], principal: Principal, thread_id: UUID, text: str
) -> UUID:
    cur = await conn.execute(
        """
        insert into chat.messages (tenant_id, thread_id, user_id, author, blocks)
        values (%s, %s, %s, 'director', %s)
        returning id
        """,
        (
            principal.tenant_id,
            thread_id,
            principal.user_id,
            Jsonb([{"tipo": "texto", "md": text}]),
        ),
    )
    message_id = (await returned(cur))["id"]
    # The first question names the chat, unless the director already did.
    title = text if len(text) <= TITLE_MAX else text[: TITLE_MAX - 1].rstrip() + "…"
    await conn.execute(
        """
        update chat.threads
           set title = case when title = %s then %s else title end,
               updated_at = now()
         where id = %s
        """,
        (DEFAULT_TITLE, title, thread_id),
    )
    return message_id


async def add_mawta_message(
    conn: AsyncConnection[DictRow],
    principal: Principal,
    thread_id: UUID,
    blocks: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
) -> UUID:
    cur = await conn.execute(
        """
        insert into chat.messages
          (tenant_id, thread_id, user_id, author, blocks, tool_calls, model, input_tokens, output_tokens, latency_ms)
        values (%s, %s, %s, 'mawta', %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (
            principal.tenant_id,
            thread_id,
            principal.user_id,
            Jsonb(blocks),
            Jsonb(tool_calls),
            model,
            input_tokens,
            output_tokens,
            latency_ms,
        ),
    )
    message_id = (await returned(cur))["id"]
    await conn.execute("update chat.threads set updated_at = now() where id = %s", (thread_id,))
    return message_id


async def school_name(conn: AsyncConnection[DictRow]) -> str:
    cur = await conn.execute("select name from chat_api.school")
    row = await cur.fetchone()
    return row["name"] if row else "el colegio"
