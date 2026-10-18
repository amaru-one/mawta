"""The class dashboard.

Where a list has no rows the JSON is `null`, not `[]`; this module keeps
that (`rows or None`) because the UI was written against it.
"""

from datetime import date
from uuid import UUID

from psycopg import AsyncConnection

from mawta_api.db import fetch_all, fetch_one, fetch_required
from mawta_api.repo.roster import roster_as_of


async def _get_class_info(conn: AsyncConnection, class_id: UUID) -> dict:
    return await fetch_required(
        conn,
        """
        select c.id, c.name, c.section_id, s.is_tutoria
          from classes c
          join courses co on co.id = c.course_id
          join subjects s on s.id = co.subject_id
         where c.id = %s and c.deleted_at is null
        """,
        (class_id,),
    )


def _session_summary(row: dict, past: bool = False, upcoming_list: bool = False) -> dict:
    out = {
        "session_id": row["id"],
        "session_date": row["session_date"].isoformat(),
        "scheduled_start_at": row["scheduled_start_at"],
        "scheduled_end_at": row["scheduled_end_at"],
        "topic": row["topic"],
        "status": row["status"],
    }
    if past:
        out["present_count"] = row["present_count"]
        out["roster_count"] = row["roster_count"]
        out["missing_grades"] = row["missing"]
        out["has_comments"] = row["has_comments"]
    return out


async def get_class_dashboard(
    conn: AsyncConnection, class_id: UUID, term: dict, today: date
) -> dict:
    cls = await _get_class_info(conn, class_id)
    roster = await roster_as_of(conn, class_id, today)

    sessions_per_week = (
        await fetch_required(
            conn,
            """
            select count(*) as n from class_schedules
             where class_id = %(class)s and effective_from <= %(today)s
               and (effective_to is null or effective_to > %(today)s)
               and deleted_at is null
            """,
            {"class": class_id, "today": today},
        )
    )["n"]

    # next_session: today's earliest session that has not yet ended. A class can meet more
    # than once in a day, so this is a wall-clock pick (scheduled_end_at >= now()). The
    # status filter keeps a cancelled/rescheduled session out of the hero.
    ns_row = await fetch_one(
        conn,
        """
        select id, session_date, scheduled_start_at, scheduled_end_at, topic, status
          from class_sessions
         where class_id = %(class)s and session_date = %(today)s
           and status in ('scheduled','in_progress')
           and scheduled_end_at >= now()
           and deleted_at is null
         order by scheduled_start_at limit 1
        """,
        {"class": class_id, "today": today},
    )
    next_session = _session_summary(ns_row) if ns_row else None

    # stats: notas registradas. A per-student assessment counts once, for its own student,
    # not once per student on the roster.
    counts = await fetch_required(
        conn,
        """
        with due as (
          select id, student_id from assessments
           where class_id = %(class)s and term_id = %(term)s and status = 'published'
             and deleted_at is null
        ),
        roster_ids as (select unnest(%(roster)s::uuid[]) as student_id),
        expected as (
          select d.id, r.student_id
            from due d cross join roster_ids r
           where d.student_id is null or d.student_id = r.student_id
        )
        select
          (select count(*) from expected) as denom,
          (select count(*) from expected e
             where exists (
               select 1 from scores s
                where s.assessment_id = e.id and s.student_id = e.student_id
                  and s.superseded_at is null and s.deleted_at is null
             )) as scored
        """,
        {"class": class_id, "term": term["id"], "roster": roster},
    )

    att = await fetch_required(
        conn,
        """
        select count(*) filter (where status in ('present','late')) as present, count(*) as total
          from attendance_records
         where class_id = %(class)s and session_date between %(from)s and %(to)s
           and deleted_at is null
        """,
        {"class": class_id, "from": term["starts_on"], "to": term["ends_on"]},
    )
    asistencia = att["present"] / att["total"] if att["total"] > 0 else None

    distribution: list[dict] = []
    if not cls["is_tutoria"]:
        rows = await fetch_all(
            conn,
            """
            select l.code, l.ordinal, count(*) as n
              from competency_term_levels ctl
              join grade_scale_levels l on l.id = ctl.scale_level_id
             where ctl.class_id = %(class)s and ctl.term_id = %(term)s
               and ctl.superseded_at is null and ctl.deleted_at is null
             group by l.code, l.ordinal
             order by l.ordinal desc
            """,
            {"class": class_id, "term": term["id"]},
        )
        distribution = [{"code": r["code"], "count": r["n"]} for r in rows]

    # pendientes: evidences past their due date with no valuation yet for some student.
    pending = await fetch_all(
        conn,
        """
        select a.id as assessment_id, a.title, count(*) as missing
          from assessments a
          cross join unnest(%(roster)s::uuid[]) as r(student_id)
          left join scores s on s.assessment_id = a.id and s.student_id = r.student_id
                             and s.superseded_at is null and s.deleted_at is null
         where a.class_id = %(class)s and a.term_id = %(term)s and a.status = 'published'
           and a.due_at is not null and a.due_at <= now() and a.deleted_at is null
           and (a.student_id is null or a.student_id = r.student_id)
           and s.id is null
         group by a.id, a.title
         having count(*) > 0
         order by a.title
        """,
        {"class": class_id, "term": term["id"], "roster": roster},
    )

    unmarked = await fetch_all(
        conn,
        """
        select id as session_id, session_date from class_sessions
         where class_id = %s and attendance_taken_at is null
           and status in ('in_progress','completed') and deleted_at is null
         order by session_date desc
        """,
        (class_id,),
    )

    upcoming = await _list_sessions(conn, class_id, today, "upcoming", 10)
    # A later, not-yet-ended session today is legitimately "próxima", but the earliest such
    # session is already the hero: drop that one row so it is not shown twice.
    if ns_row and upcoming is not None:
        upcoming = [s for s in upcoming if s["session_id"] != ns_row["id"]]
    past = await _list_sessions(conn, class_id, today, "past", 10)

    return {
        "class_id": cls["id"],
        "name": cls["name"],
        "is_tutoria": cls["is_tutoria"],
        "roster_count": len(roster),
        "sessions_per_week": sessions_per_week,
        "term_id": term["id"],
        "next_session": next_session,
        "stats": {
            "scored": counts["scored"],
            "expected": counts["denom"],
            "asistencia_pct": asistencia,
        },
        "distribution": distribution or None,
        "grades_pending": [
            {"assessment_id": r["assessment_id"], "title": r["title"], "missing": r["missing"]}
            for r in pending
        ]
        or None,
        "attendance_unmarked": [
            {"session_id": r["session_id"], "session_date": r["session_date"].isoformat()}
            for r in unmarked
        ]
        or None,
        "upcoming": upcoming,
        "past": past,
    }


_PAST_SQL = """
    select cs.id, cs.session_date, cs.scheduled_start_at, cs.scheduled_end_at, cs.topic, cs.status,
           att.present_count, att.roster_count, coalesce(pg.missing, 0) as missing,
           exists (
             select 1 from voice_notes vn
              where vn.session_id = cs.id and vn.deleted_at is null
           ) as has_comments
      from class_sessions cs
      cross join lateral (
        select
          (select count(*) from attendance_records ar
            where ar.session_id = cs.id and ar.status in ('present','late')
              and ar.deleted_at is null) as present_count,
          (select count(*) from section_memberships sm
             join classes c on c.section_id = sm.section_id
            where c.id = cs.class_id
              and sm.joined_on <= cs.session_date
              and (sm.left_on is null or sm.left_on > cs.session_date)
              and sm.deleted_at is null) as roster_count
      ) att
      left join lateral (
        select count(*) as missing
          from assessments a
          join classes c on c.id = a.class_id
          join section_memberships sm on sm.section_id = c.section_id
           and sm.joined_on <= cs.session_date
           and (sm.left_on is null or sm.left_on > cs.session_date)
           and sm.deleted_at is null
          left join scores s on s.assessment_id = a.id and s.student_id = sm.student_id
                             and s.superseded_at is null and s.deleted_at is null
         where a.session_id = cs.id and a.status = 'published' and a.deleted_at is null
           and (a.student_id is null or a.student_id = sm.student_id)
           and s.id is null
      ) pg on true
     where cs.class_id = %(class)s and cs.deleted_at is null
       and (cs.session_date < %(d)s::date
            or (cs.session_date = %(d)s::date and cs.scheduled_end_at < now()))
     order by cs.session_date desc, cs.scheduled_start_at desc
     limit %(limit)s
"""

_UPCOMING_SQL = """
    select cs.id, cs.session_date, cs.scheduled_start_at, cs.scheduled_end_at, cs.topic, cs.status
      from class_sessions cs
     where cs.class_id = %(class)s and cs.deleted_at is null
       and (cs.session_date > %(d)s::date
            or (cs.session_date = %(d)s::date and cs.scheduled_end_at >= now()))
     order by cs.session_date asc, cs.scheduled_start_at asc
     limit %(limit)s
"""


async def _list_sessions(
    conn: AsyncConnection, class_id: UUID, d: date, direction: str, limit: int
) -> list[dict] | None:
    """Upcoming (ascending) or past (descending) sessions. The split is by wall clock, not by
    date alone. Past rows carry attendance and pending-grade chips. None when empty."""
    past = direction == "past"
    rows = await fetch_all(
        conn,
        _PAST_SQL if past else _UPCOMING_SQL,
        {"class": class_id, "d": d, "limit": limit},
    )
    return [_session_summary(r, past=past) for r in rows] or None
