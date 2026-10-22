"""Connection to the mawta database as the mawta_chat role.

Every query runs inside tenant_tx, which sets app.tenant_id and app.actor_id
for the transaction. Postgres RLS does the isolation: the chat_api views show
only the director's school, and chat.threads/messages only their own chats.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from auth import Principal


class Database:
    pool: AsyncConnectionPool[AsyncConnection[DictRow]]

    def __init__(self, url: str, max_size: int = 5) -> None:
        # mawta_chat has a connection limit of 10 (migration 00006).
        self.pool = AsyncConnectionPool(
            url,
            min_size=1,
            max_size=max_size,
            open=False,
            connection_class=AsyncConnection[DictRow],
            kwargs={"row_factory": dict_row},
        )

    async def open(self) -> None:
        await self.pool.open(wait=True)

    async def close(self) -> None:
        await self.pool.close()

    @asynccontextmanager
    async def tenant_tx(self, principal: Principal) -> AsyncGenerator[AsyncConnection[DictRow]]:
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(
                "select set_config('app.tenant_id', %s, true), set_config('app.actor_id', %s, true)",
                (str(principal.tenant_id), str(principal.user_id)),
            )
            yield conn
