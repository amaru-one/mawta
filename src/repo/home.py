"""The teacher's home screen and the school's calendar day."""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Date, SmallInteger, cast, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_all, scalar
from mawta_schema.tables import Class, ClassSession, ClassTeacher, Course, School, Subject


async def school_today(conn: AsyncConnection) -> date:
    """ "Today" as a date in the school's IANA timezone: the only place a local calendar
    day is defined in this schema."""
    return await scalar(conn, select(cast(func.timezone(School.timezone, func.now()), Date)))


def _home_class(row: Any) -> dict[str, Any]:
    return {
        "class_id": row["class_id"],
        "name": row["name"],
        "icon_key": row["icon_key"],
        "is_tutoria": row["is_tutoria"],
    }


async def _my_classes(conn: AsyncConnection, teacher_id: UUID, d: date) -> list[Any]:
    return await fetch_all(
        conn,
        select(Class.id.label("class_id"), Class.name, Subject.icon_key, Subject.is_tutoria)
        .distinct()
        .select_from(ClassTeacher)
        .join(
            Class,
            (Class.id == ClassTeacher.class_id)
            & Class.deleted_at.is_(None)
            & (Class.status == "active"),
        )
        .join(Course, Course.id == Class.course_id)
        .join(Subject, Subject.id == Course.subject_id)
        .where(
            ClassTeacher.teacher_id == teacher_id,
            ClassTeacher.starts_on <= d,
            or_(ClassTeacher.ends_on.is_(None), ClassTeacher.ends_on >= d),
            ClassTeacher.deleted_at.is_(None),
        )
        .order_by(Class.name),
    )


_SESSION = (
    ClassSession.class_id,
    ClassSession.id,
    ClassSession.scheduled_start_at,
    ClassSession.scheduled_end_at,
    ClassSession.status,
    ClassSession.room,
    ClassSession.topic,
)


def _session(row: Any, by_id: dict[UUID, dict[str, Any]]) -> dict[str, Any]:
    return {
        **by_id[row["class_id"]],
        "session_id": row["id"],
        "scheduled_start_at": row["scheduled_start_at"],
        "scheduled_end_at": row["scheduled_end_at"],
        "status": row["status"],
        "room": row["room"],
        "topic": row["topic"],
    }


async def get_home(conn: AsyncConnection, teacher_id: UUID, d: date) -> dict[str, Any]:
    # An empty list is JSON null here: the UI was written against that.
    resp: dict[str, Any] = {"date": d.isoformat(), "today": None, "week": None}

    classes = await _my_classes(conn, teacher_id, d)
    if not classes:
        return resp
    class_ids = [c["class_id"] for c in classes]
    by_id = {c["class_id"]: _home_class(c) for c in classes}

    # Status is deliberately not filtered: home shows the day as it stands, cancelled and
    # finished sessions included. The client renders those states, it does not hide them.
    rows = await fetch_all(
        conn,
        select(*_SESSION)
        .where(
            ClassSession.class_id.in_(class_ids),
            ClassSession.session_date == d,
            ClassSession.deleted_at.is_(None),
        )
        .order_by(ClassSession.scheduled_start_at),
    )
    if rows:
        resp["today"] = [_session(r, by_id) for r in rows]

    # The rest of the ISO week (it starts on Monday, the weekday convention the schema uses)
    # as concrete dated sessions. A class that also meets today appears in both buckets: the
    # week is an agenda of days.
    monday = d - timedelta(days=d.isoweekday() - 1)
    rows = await fetch_all(
        conn,
        select(
            *_SESSION,
            ClassSession.session_date,
            cast(extract("isodow", ClassSession.session_date), SmallInteger).label("weekday"),
        )
        .where(
            ClassSession.class_id.in_(class_ids),
            ClassSession.deleted_at.is_(None),
            ClassSession.session_date >= monday,
            ClassSession.session_date < monday + timedelta(days=7),
            ClassSession.session_date != d,
        )
        .order_by(ClassSession.session_date, ClassSession.scheduled_start_at),
    )
    week: list[dict[str, Any]] = []
    for r in rows:
        day = r["session_date"].isoformat()
        if not week or week[-1]["date"] != day:
            week.append({"date": day, "weekday": r["weekday"], "sessions": []})
        week[-1]["sessions"].append(_session(r, by_id))
    resp["week"] = week or None
    return resp
