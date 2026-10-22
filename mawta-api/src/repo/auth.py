"""Login candidates, memberships and sessions."""

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from db import fetch_one, fetch_required

# ── pre-tenant, via Database.auth_tx ────────────────────────────────────


async def find_login_candidate(
    conn: AsyncConnection[DictRow], username: str
) -> dict[str, Any] | None:
    """The user matching lower(username): id, password_hash, status, locked_until.
    None when there is no match; the caller must still verify against the dummy hash."""
    return await fetch_one(
        conn,
        """
        select id as user_id, password_hash, status, locked_until
          from users
         where lower(username) = lower(%s) and password_hash is not null and deleted_at is null
        """,
        (username,),
    )


async def resolve_membership(
    conn: AsyncConnection[DictRow], user_id: UUID
) -> dict[str, Any] | None:
    """The user's single non-revoked membership (memberships_one_school_per_user)."""
    return await fetch_one(
        conn,
        """
        select tenant_id, id as membership_id, role
          from memberships
         where user_id = %s and deleted_at is null and status <> 'revoked'
        """,
        (user_id,),
    )


async def record_login_failure(
    conn: AsyncConnection[DictRow], user_id: UUID, max_failures: int, lock_seconds: float
) -> None:
    await conn.execute(
        """
        update users
           set failed_login_count = failed_login_count + 1,
               locked_until = case when failed_login_count + 1 >= %(max)s
                                   then now() + make_interval(secs => %(secs)s)
                                   else locked_until
                              end
         where id = %(id)s
        """,
        {"id": user_id, "max": max_failures, "secs": lock_seconds},
    )


async def record_login_success(conn: AsyncConnection[DictRow], user_id: UUID) -> None:
    await conn.execute(
        """
        update users
           set failed_login_count = 0, locked_until = null, last_login_at = now()
         where id = %s
        """,
        (user_id,),
    )


async def create_session(
    conn: AsyncConnection[DictRow],
    *,
    token_hash: bytes,
    user_id: UUID,
    tenant_id: UUID,
    membership_id: UUID,
    role: str,
    expires_at: datetime,
    user_agent: str,
    ip: str | None,
) -> UUID:
    row = await fetch_required(
        conn,
        """
        insert into user_sessions (token_hash, user_id, tenant_id, membership_id, role,
                                   expires_at, user_agent, ip)
        values (%s, %s, %s, %s, %s, %s, nullif(%s, ''), %s::inet)
        returning id
        """,
        (token_hash, user_id, tenant_id, membership_id, role, expires_at, user_agent, ip),
    )
    return row["id"]


async def find_live_session(
    conn: AsyncConnection[DictRow], token_hash: bytes
) -> dict[str, Any] | None:
    """By exact token hash where revoked_at is null. None covers both "no such
    session" and "already revoked"."""
    return await fetch_one(
        conn,
        """
        select id, user_id, tenant_id, membership_id, role, last_seen_at, expires_at
          from user_sessions
         where token_hash = %s and revoked_at is null
        """,
        (token_hash,),
    )


async def touch_session(
    conn: AsyncConnection[DictRow], session_id: UUID, min_interval: float
) -> None:
    """Bump last_seen_at only if it's older than min_interval: called on every
    request, so a write per request would make every GET a read-write transaction."""
    await conn.execute(
        """
        update user_sessions
           set last_seen_at = now()
         where id = %(id)s and last_seen_at < now() - make_interval(secs => %(secs)s)
        """,
        {"id": session_id, "secs": min_interval},
    )


async def revoke_session(conn: AsyncConnection[DictRow], session_id: UUID, reason: str) -> None:
    await conn.execute(
        """
        update user_sessions set revoked_at = now(), revoked_reason = %s
         where id = %s and revoked_at is null
        """,
        (reason, session_id),
    )


async def revoke_session_by_token_hash(
    conn: AsyncConnection[DictRow], token_hash: bytes, reason: str
) -> None:
    await conn.execute(
        """
        update user_sessions set revoked_at = now(), revoked_reason = %s
         where token_hash = %s and revoked_at is null
        """,
        (reason, token_hash),
    )


async def revoke_user_sessions(conn: AsyncConnection[DictRow], user_id: UUID, reason: str) -> None:
    """Every live session of a user: called on a password change."""
    await conn.execute(
        """
        update user_sessions set revoked_at = now(), revoked_reason = %s
         where user_id = %s and revoked_at is null
        """,
        (reason, user_id),
    )


async def prune_sessions(conn: AsyncConnection[DictRow], retain_seconds: float) -> int:
    """Hard-delete rows revoked or expired more than retain ago, opportunistically at login."""
    cur = await conn.execute(
        """
        delete from user_sessions
         where (revoked_at is not null and revoked_at < now() - make_interval(secs => %(s)s))
            or expires_at < now() - make_interval(secs => %(s)s)
        """,
        {"s": retain_seconds},
    )
    return cur.rowcount


# ── post-tenant, via Database.tenant_tx ─────────────────────────────────


async def resolve_teacher(conn: AsyncConnection[DictRow], user_id: UUID) -> UUID | None:
    """The membership must still be active and still carry a teachers row."""
    row = await fetch_one(
        conn,
        """
        select t.id
          from memberships m
          join teachers t on t.membership_id = m.id and t.deleted_at is null
         where m.user_id = %s
           and m.tenant_id = app.current_tenant_id()
           and m.status = 'active'
           and m.deleted_at is null
        """,
        (user_id,),
    )
    return row["id"] if row else None
