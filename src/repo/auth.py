"""Login candidates, memberships and sessions."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import case, delete, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_one, fetch_required
from mawta_schema.tables import Membership, Teacher, User, UserSession

# ── before anyone is known, via Database.auth_tx ────────────────────────


async def find_login_candidate(conn: AsyncConnection, username: str) -> dict[str, Any] | None:
    """The user matching lower(username): id, password_hash, status, locked_until.
    None when there is no match; the caller must still verify against the dummy hash."""
    row = await fetch_one(
        conn,
        select(User.id.label("user_id"), User.password_hash, User.status, User.locked_until).where(
            func.lower(User.username) == func.lower(username),
            User.password_hash.is_not(None),
            User.deleted_at.is_(None),
        ),
    )
    return dict(row) if row else None


async def resolve_membership(conn: AsyncConnection, user_id: UUID) -> dict[str, Any] | None:
    """The user's single non-revoked membership (memberships_one_school_per_user)."""
    row = await fetch_one(
        conn,
        select(Membership.id.label("membership_id"), Membership.role).where(
            Membership.user_id == user_id,
            Membership.deleted_at.is_(None),
            Membership.status != "revoked",
        ),
    )
    return dict(row) if row else None


async def record_login_failure(
    conn: AsyncConnection, user_id: UUID, max_failures: int, lock_seconds: float
) -> None:
    await conn.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            failed_login_count=User.failed_login_count + 1,
            locked_until=case(
                (
                    User.failed_login_count + 1 >= max_failures,
                    func.now() + timedelta(seconds=lock_seconds),
                ),
                else_=User.locked_until,
            ),
        )
    )


async def record_login_success(conn: AsyncConnection, user_id: UUID) -> None:
    await conn.execute(
        update(User)
        .where(User.id == user_id)
        .values(failed_login_count=0, locked_until=None, last_login_at=func.now())
    )


async def create_session(
    conn: AsyncConnection,
    *,
    token_hash: bytes,
    user_id: UUID,
    membership_id: UUID,
    role: str,
    expires_at: datetime,
    user_agent: str,
    ip: str | None,
) -> UUID:
    row = await fetch_required(
        conn,
        insert(UserSession)
        .values(
            token_hash=token_hash,
            user_id=user_id,
            membership_id=membership_id,
            role=role,
            expires_at=expires_at,
            user_agent=user_agent or None,
            ip=ip,
        )
        .returning(UserSession.id),
    )
    return row["id"]


async def find_live_session(conn: AsyncConnection, token_hash: bytes) -> dict[str, Any] | None:
    """By exact token hash where revoked_at is null. None covers both "no such
    session" and "already revoked"."""
    row = await fetch_one(
        conn,
        select(
            UserSession.id,
            UserSession.user_id,
            UserSession.membership_id,
            UserSession.role,
            UserSession.last_seen_at,
            UserSession.expires_at,
        ).where(UserSession.token_hash == token_hash, UserSession.revoked_at.is_(None)),
    )
    return dict(row) if row else None


async def touch_session(conn: AsyncConnection, session_id: UUID, min_interval: float) -> None:
    """Bump last_seen_at only if it's older than min_interval: called on every
    request, so a write per request would make every GET a read-write transaction."""
    await conn.execute(
        update(UserSession)
        .where(
            UserSession.id == session_id,
            UserSession.last_seen_at < func.now() - timedelta(seconds=min_interval),
        )
        .values(last_seen_at=func.now())
    )


def _revoke(reason: str):
    return (
        update(UserSession)
        .where(UserSession.revoked_at.is_(None))
        .values(revoked_at=func.now(), revoked_reason=reason)
    )


async def revoke_session(conn: AsyncConnection, session_id: UUID, reason: str) -> None:
    await conn.execute(_revoke(reason).where(UserSession.id == session_id))


async def revoke_session_by_token_hash(
    conn: AsyncConnection, token_hash: bytes, reason: str
) -> None:
    await conn.execute(_revoke(reason).where(UserSession.token_hash == token_hash))


async def revoke_user_sessions(conn: AsyncConnection, user_id: UUID, reason: str) -> None:
    """Every live session of a user: called on a password change."""
    await conn.execute(_revoke(reason).where(UserSession.user_id == user_id))


async def prune_sessions(conn: AsyncConnection, retain_seconds: float) -> int:
    """Hard-delete rows revoked or expired more than retain ago, opportunistically at login."""
    cutoff = func.now() - timedelta(seconds=retain_seconds)
    result = await conn.execute(
        delete(UserSession).where(
            or_(
                UserSession.revoked_at.is_not(None) & (UserSession.revoked_at < cutoff),
                UserSession.expires_at < cutoff,
            )
        )
    )
    return result.rowcount


# ── once the session is known, via Database.user_tx ─────────────────────


async def resolve_teacher(conn: AsyncConnection, user_id: UUID) -> UUID | None:
    """The membership must still be active and still carry a teachers row."""
    row = await fetch_one(
        conn,
        select(Teacher.id)
        .select_from(Membership)
        .join(Teacher, (Teacher.membership_id == Membership.id) & Teacher.deleted_at.is_(None))
        .where(
            Membership.user_id == user_id,
            Membership.status == "active",
            Membership.deleted_at.is_(None),
        ),
    )
    return row["id"] if row else None
