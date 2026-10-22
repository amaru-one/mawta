"""The /me payload."""

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

import domain
from db import fetch_required

_ZERO_UUID = UUID(int=0)


def _payload(
    row: dict[str, Any], teacher_id: UUID | None, teacher_title: str | None
) -> dict[str, Any]:
    return {
        "role": "",
        "user": {"display_name": row["display_name"], "email": row["email"]},
        "teacher": {"id": teacher_id or _ZERO_UUID, "title": teacher_title},
        "tenant": {
            "id": row["tenant_id"],
            "name": row["tenant_name"],
            "city": row["city"],
            "timezone": row["timezone"],
        },
    }


async def get_me(conn: AsyncConnection[DictRow], teacher_id: UUID) -> dict[str, Any]:
    row = await fetch_required(
        conn,
        """
        select coalesce(u.display_name, u.given_name || ' ' || u.family_name) as display_name,
               u.email, t.title as teacher_title,
               tn.id as tenant_id, tn.name as tenant_name, tn.city, tn.timezone
          from teachers t
          join memberships m on m.id = t.membership_id
          join users u on u.id = m.user_id
          join tenants tn on tn.id = t.tenant_id
         where t.id = %s
        """,
        (teacher_id,),
    )
    return _payload(row, teacher_id, row["teacher_title"])


async def get_director_me(conn: AsyncConnection[DictRow], user_id: UUID) -> dict[str, Any]:
    """get_me for a director, who has no teachers row: the teacher part stays empty."""
    row = await fetch_required(
        conn,
        """
        select coalesce(u.display_name, u.given_name || ' ' || u.family_name) as display_name,
               u.email,
               tn.id as tenant_id, tn.name as tenant_name, tn.city, tn.timezone
          from memberships m
          join users u on u.id = m.user_id
          join tenants tn on tn.id = m.tenant_id
         where m.user_id = %s
           and m.role = %s
           and m.tenant_id = app.current_tenant_id()
           and m.status = 'active'
           and m.deleted_at is null
        """,
        (user_id, domain.ROLE_DIRECTOR),
    )
    return _payload(row, None, None)
