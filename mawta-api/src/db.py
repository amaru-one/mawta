"""The connection pool and the per-transaction tenant context every RLS-protected
query goes through.

Each helper yields a psycopg AsyncConnection inside one transaction. SET LOCAL
semantics make the role and GUCs evaporate at commit/rollback, so pooled
connections never leak tenant context between requests or jobs. Forgetting the
context is silent with FORCE ROW LEVEL SECURITY (zero rows, no error), so repo
code only ever receives a connection from one of these helpers.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.abc import Params, QueryNoTemplate
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class TenantCtx:
    """The RLS session context for one request or job."""

    tenant_id: UUID
    actor_id: UUID | None = None  # None when acting as a system/job
    teacher_id: UUID | None = None
    request_id: str = ""
    role: str = ""  # the acting user_sessions.role; empty for a system/job actor

    def with_teacher(self, teacher_id: UUID) -> "TenantCtx":
        return replace(self, teacher_id=teacher_id)


class Database:
    pool: AsyncConnectionPool[AsyncConnection[DictRow]]

    def __init__(self, url: str, max_size: int = 10) -> None:
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

    async def ping(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("select 1")

    @asynccontextmanager
    async def tenant_tx(self, tc: TenantCtx) -> AsyncGenerator[AsyncConnection[DictRow]]:
        """Drop to the non-owner mawta_app role and set app.tenant_id/actor_id/request_id."""
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("set local role mawta_app")
            await conn.execute(
                "select set_config('app.tenant_id', %s, true),"
                " set_config('app.actor_id', %s, true),"
                " set_config('app.request_id', %s, true)",
                (str(tc.tenant_id), str(tc.actor_id) if tc.actor_id else "", tc.request_id),
            )
            yield conn

    @asynccontextmanager
    async def auth_tx(self, request_id: str = "") -> AsyncGenerator[AsyncConnection[DictRow]]:
        """mawta_app with no tenant and app.auth_lookup='on': the one mode that can
        read a users/user_sessions row before a tenant is known."""
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("set local role mawta_app")
            await conn.execute(
                "select set_config('app.auth_lookup', 'on', true),"
                " set_config('app.request_id', %s, true)",
                (request_id,),
            )
            yield conn

    @asynccontextmanager
    async def system_tx(self) -> AsyncGenerator[AsyncConnection[DictRow]]:
        """A transaction as the pool's own role: no role drop, no tenant GUCs.

        Safe on `jobs` (no RLS) under any role; on tenant tables it needs a
        connection that bypasses row security, which `useradd` and `onboard`
        open from ADMIN_DATABASE_URL. Never use it for request data.
        """
        async with self.pool.connection() as conn, conn.transaction():
            yield conn


def returned(row: DictRow | None) -> DictRow:
    """The row of a statement that always yields one (insert ... returning, an aggregate).
    None here is a bug, not a lookup that matched nothing (that is fetch_required)."""
    if row is None:
        raise RuntimeError("the statement returned no row")
    return row


async def fetch_one(
    conn: AsyncConnection[DictRow], sql: QueryNoTemplate, params: Params | None = None
) -> DictRow | None:
    cur = await conn.execute(sql, params)
    return await cur.fetchone()


async def fetch_all(
    conn: AsyncConnection[DictRow], sql: QueryNoTemplate, params: Params | None = None
) -> list[DictRow]:
    cur = await conn.execute(sql, params)
    return await cur.fetchall()


async def fetch_required(
    conn: AsyncConnection[DictRow], sql: QueryNoTemplate, params: Params | None = None
) -> DictRow:
    """fetch_one, but no row raises NotFound (a lookup that matched nothing)."""
    from errors import NotFound

    row = await fetch_one(conn, sql, params)
    if row is None:
        raise NotFound
    return row
