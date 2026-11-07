"""The /me payload."""

from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

import domain
from db import fetch_required
from mawta_schema.tables import Membership, School, Teacher, User

_ZERO_UUID = UUID(int=0)

_DISPLAY_NAME = func.coalesce(User.display_name, User.given_name + " " + User.family_name).label(
    "display_name"
)
_SCHOOL = (School.name.label("school_name"), School.city, School.timezone)


def _payload(row: RowMapping, teacher_id: UUID | None, teacher_title: str | None) -> dict[str, Any]:
    return {
        "role": "",
        "user": {"display_name": row["display_name"], "email": row["email"]},
        "teacher": {"id": teacher_id or _ZERO_UUID, "title": teacher_title},
        "school": {"name": row["school_name"], "city": row["city"], "timezone": row["timezone"]},
    }


async def get_me(conn: AsyncConnection, teacher_id: UUID) -> dict[str, Any]:
    row = await fetch_required(
        conn,
        select(_DISPLAY_NAME, User.email, Teacher.title.label("teacher_title"), *_SCHOOL)
        .select_from(Teacher)
        .join(Membership, Membership.id == Teacher.membership_id)
        .join(User, User.id == Membership.user_id)
        .join_from(Teacher, School, School.singleton.is_(True))
        .where(Teacher.id == teacher_id),
    )
    return _payload(row, teacher_id, row["teacher_title"])


async def get_director_me(conn: AsyncConnection, user_id: UUID) -> dict[str, Any]:
    """get_me for a director, who has no teachers row: the teacher part stays empty."""
    row = await fetch_required(
        conn,
        select(_DISPLAY_NAME, User.email, *_SCHOOL)
        .select_from(Membership)
        .join(User, User.id == Membership.user_id)
        .join_from(Membership, School, School.singleton.is_(True))
        .where(
            Membership.user_id == user_id,
            Membership.role == domain.ROLE_DIRECTOR,
            Membership.status == "active",
            Membership.deleted_at.is_(None),
        ),
    )
    return _payload(row, None, None)
