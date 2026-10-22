"""The teacher's home screen and the tenant calendar day."""

from datetime import date
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from db import fetch_all, fetch_required


async def tenant_today(conn: AsyncConnection[DictRow], tenant_id: UUID) -> date:
    """ "Today" as a date in the tenant's IANA timezone: the only place a local calendar
    day is defined in this schema."""
    row = await fetch_required(
        conn,
        "select (now() at time zone tn.timezone)::date as today from tenants tn where tn.id = %s",
        (tenant_id,),
    )
    return row["today"]


def _home_class(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "class_id": row["class_id"],
        "name": row["name"],
        "icon_key": row["icon_key"],
        "is_tutoria": row["is_tutoria"],
    }


async def _my_classes(
    conn: AsyncConnection[DictRow], teacher_id: UUID, d: date
) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        select distinct c.id as class_id, c.name, s.icon_key, s.is_tutoria
          from class_teachers ct
          join classes c on c.id = ct.class_id and c.deleted_at is null and c.status = 'active'
          join courses co on co.id = c.course_id
          join subjects s on s.id = co.subject_id
         where ct.teacher_id = %(teacher)s
           and ct.starts_on <= %(d)s
           and (ct.ends_on is null or ct.ends_on >= %(d)s)
           and ct.deleted_at is null
         order by c.name
        """,
        {"teacher": teacher_id, "d": d},
    )


async def get_home(conn: AsyncConnection[DictRow], teacher_id: UUID, d: date) -> dict[str, Any]:
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
        """
        select class_id, id, scheduled_start_at, scheduled_end_at, status, room, topic
          from class_sessions
         where class_id = any(%(ids)s::uuid[]) and session_date = %(d)s and deleted_at is null
         order by scheduled_start_at
        """,
        {"ids": class_ids, "d": d},
    )
    if rows:
        resp["today"] = [
            {
                **by_id[r["class_id"]],
                "session_id": r["id"],
                "scheduled_start_at": r["scheduled_start_at"],
                "scheduled_end_at": r["scheduled_end_at"],
                "status": r["status"],
                "room": r["room"],
                "topic": r["topic"],
            }
            for r in rows
        ]

    # The rest of the ISO week (date_trunc('week') starts Monday, the weekday convention the
    # schema uses) as concrete dated sessions. A class that also meets today appears in both
    # buckets: the week is an agenda of days.
    rows = await fetch_all(
        conn,
        """
        select cs.class_id, cs.id, cs.session_date,
               extract(isodow from cs.session_date)::smallint as weekday,
               cs.scheduled_start_at, cs.scheduled_end_at, cs.status, cs.room, cs.topic
          from class_sessions cs
         where cs.class_id = any(%(ids)s::uuid[])
           and cs.deleted_at is null
           and cs.session_date >= date_trunc('week', %(d)s::date)::date
           and cs.session_date <  date_trunc('week', %(d)s::date)::date + 7
           and cs.session_date <> %(d)s::date
         order by cs.session_date, cs.scheduled_start_at
        """,
        {"ids": class_ids, "d": d},
    )
    week: list[dict[str, Any]] = []
    for r in rows:
        day = r["session_date"].isoformat()
        if not week or week[-1]["date"] != day:
            week.append({"date": day, "weekday": r["weekday"], "sessions": []})
        week[-1]["sessions"].append(
            {
                **by_id[r["class_id"]],
                "session_id": r["id"],
                "scheduled_start_at": r["scheduled_start_at"],
                "scheduled_end_at": r["scheduled_end_at"],
                "status": r["status"],
                "room": r["room"],
                "topic": r["topic"],
            }
        )
    resp["week"] = week or None
    return resp
