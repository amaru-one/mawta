"""The class dashboard.

Where a list has no rows the JSON is `null`, not `[]`; this module keeps
that (`rows or None`) because the UI was written against it.
"""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, RowMapping, func, literal, or_, select, true
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_all, fetch_one, fetch_required, scalar
from mawta_schema.tables import (
    Assessment,
    AttendanceRecord,
    Class,
    ClassSchedule,
    ClassSession,
    CompetencyTermLevel,
    Course,
    GradeScaleLevel,
    Score,
    SectionMembership,
    Subject,
    VoiceNote,
)
from repo.roster import roster_as_of


async def _get_class_info(conn: AsyncConnection, class_id: UUID) -> dict[str, Any]:
    row = await fetch_required(
        conn,
        select(Class.id, Class.name, Class.section_id, Subject.is_tutoria)
        .join(Course, Course.id == Class.course_id)
        .join(Subject, Subject.id == Course.subject_id)
        .where(Class.id == class_id, Class.deleted_at.is_(None)),
    )
    return dict(row)


def _session_summary(row: RowMapping, past: bool = False) -> dict[str, Any]:
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


def _roster(student_ids: list[UUID]):
    """The roster as a table, r(student_id)."""
    return (
        func.unnest(literal(student_ids, ARRAY(PgUUID(as_uuid=True))))
        .table_valued("student_id")
        .render_derived(name="r")
    )


def _live_score(student_id: Any) -> ColumnElement[bool]:
    return (
        (Score.assessment_id == Assessment.id)
        & (Score.student_id == student_id)
        & Score.superseded_at.is_(None)
        & Score.deleted_at.is_(None)
    )


async def get_class_dashboard(
    conn: AsyncConnection, class_id: UUID, term: dict[str, Any], today: date
) -> dict[str, Any]:
    cls = await _get_class_info(conn, class_id)
    roster = await roster_as_of(conn, class_id, today)

    sessions_per_week = await scalar(
        conn,
        select(func.count()).where(
            ClassSchedule.class_id == class_id,
            ClassSchedule.effective_from <= today,
            or_(ClassSchedule.effective_to.is_(None), ClassSchedule.effective_to > today),
            ClassSchedule.deleted_at.is_(None),
        ),
    )

    # next_session: today's earliest session that has not yet ended. A class can meet more
    # than once in a day, so this is a wall-clock pick (scheduled_end_at >= now()). The
    # status filter keeps a cancelled/rescheduled session out of the hero.
    ns_row = await fetch_one(
        conn,
        select(*_SUMMARY)
        .where(
            ClassSession.class_id == class_id,
            ClassSession.session_date == today,
            ClassSession.status.in_(("scheduled", "in_progress")),
            ClassSession.scheduled_end_at >= func.now(),
            ClassSession.deleted_at.is_(None),
        )
        .order_by(ClassSession.scheduled_start_at)
        .limit(1),
    )
    next_session = _session_summary(ns_row) if ns_row else None

    # stats: notas registradas. A per-student assessment counts once, for its own student,
    # not once per student on the roster.
    due = (
        select(Assessment.id, Assessment.student_id)
        .where(
            Assessment.class_id == class_id,
            Assessment.term_id == term["id"],
            Assessment.status == "published",
            Assessment.deleted_at.is_(None),
        )
        .cte("due")
    )
    r = _roster(roster)
    expected = (
        select(due.c.id, r.c.student_id)
        .select_from(due)
        .join(r, true())
        .where(or_(due.c.student_id.is_(None), due.c.student_id == r.c.student_id))
        .cte("expected")
    )
    scored = (
        select(func.count())
        .select_from(expected)
        .where(
            select(1)
            .where(
                Score.assessment_id == expected.c.id,
                Score.student_id == expected.c.student_id,
                Score.superseded_at.is_(None),
                Score.deleted_at.is_(None),
            )
            .exists()
        )
    )
    counts = await fetch_required(
        conn,
        select(
            select(func.count()).select_from(expected).scalar_subquery().label("denom"),
            scored.scalar_subquery().label("scored"),
        ),
    )

    att = await fetch_required(
        conn,
        select(
            func.count().filter(AttendanceRecord.status.in_(("present", "late"))).label("present"),
            func.count().label("total"),
        ).where(
            AttendanceRecord.class_id == class_id,
            AttendanceRecord.session_date.between(term["starts_on"], term["ends_on"]),
            AttendanceRecord.deleted_at.is_(None),
        ),
    )
    asistencia = att["present"] / att["total"] if att["total"] > 0 else None

    distribution: list[dict[str, Any]] = []
    if not cls["is_tutoria"]:
        rows = await fetch_all(
            conn,
            select(GradeScaleLevel.code, GradeScaleLevel.ordinal, func.count().label("n"))
            .select_from(CompetencyTermLevel)
            .join(GradeScaleLevel, GradeScaleLevel.id == CompetencyTermLevel.scale_level_id)
            .where(
                CompetencyTermLevel.class_id == class_id,
                CompetencyTermLevel.term_id == term["id"],
                CompetencyTermLevel.superseded_at.is_(None),
                CompetencyTermLevel.deleted_at.is_(None),
            )
            .group_by(GradeScaleLevel.code, GradeScaleLevel.ordinal)
            .order_by(GradeScaleLevel.ordinal.desc()),
        )
        distribution = [{"code": row["code"], "count": row["n"]} for row in rows]

    # pendientes: evidences past their due date with no valuation yet for some student.
    r = _roster(roster)
    pending = await fetch_all(
        conn,
        select(
            Assessment.id.label("assessment_id"), Assessment.title, func.count().label("missing")
        )
        .select_from(Assessment)
        .join(r, true())
        .outerjoin(Score, _live_score(r.c.student_id))
        .where(
            Assessment.class_id == class_id,
            Assessment.term_id == term["id"],
            Assessment.status == "published",
            Assessment.due_at.is_not(None),
            Assessment.due_at <= func.now(),
            Assessment.deleted_at.is_(None),
            or_(Assessment.student_id.is_(None), Assessment.student_id == r.c.student_id),
            Score.id.is_(None),
        )
        .group_by(Assessment.id, Assessment.title)
        .having(func.count() > 0)
        .order_by(Assessment.title),
    )

    unmarked = await fetch_all(
        conn,
        select(ClassSession.id.label("session_id"), ClassSession.session_date)
        .where(
            ClassSession.class_id == class_id,
            ClassSession.attendance_taken_at.is_(None),
            ClassSession.status.in_(("in_progress", "completed")),
            ClassSession.deleted_at.is_(None),
        )
        .order_by(ClassSession.session_date.desc()),
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


_SUMMARY = (
    ClassSession.id,
    ClassSession.session_date,
    ClassSession.scheduled_start_at,
    ClassSession.scheduled_end_at,
    ClassSession.topic,
    ClassSession.status,
)


def _past_columns():
    """Attendance and pending-grade chips of a past session, correlated to class_sessions."""
    cs = ClassSession
    on_session_date = (
        (SectionMembership.joined_on <= cs.session_date)
        & or_(SectionMembership.left_on.is_(None), SectionMembership.left_on > cs.session_date)
        & SectionMembership.deleted_at.is_(None)
    )
    present_count = (
        select(func.count())
        .where(
            AttendanceRecord.session_id == cs.id,
            AttendanceRecord.status.in_(("present", "late")),
            AttendanceRecord.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    roster_count = (
        select(func.count())
        .select_from(SectionMembership)
        .join(Class, Class.section_id == SectionMembership.section_id)
        .where(Class.id == cs.class_id, on_session_date)
        .scalar_subquery()
    )
    missing = (
        select(func.count())
        .select_from(Assessment)
        .join(Class, Class.id == Assessment.class_id)
        .join(
            SectionMembership,
            (SectionMembership.section_id == Class.section_id) & on_session_date,
        )
        .outerjoin(Score, _live_score(SectionMembership.student_id))
        .where(
            Assessment.session_id == cs.id,
            Assessment.status == "published",
            Assessment.deleted_at.is_(None),
            or_(
                Assessment.student_id.is_(None),
                Assessment.student_id == SectionMembership.student_id,
            ),
            Score.id.is_(None),
        )
        .scalar_subquery()
    )
    has_comments = (
        select(1).where(VoiceNote.session_id == cs.id, VoiceNote.deleted_at.is_(None)).exists()
    )
    return (
        present_count.label("present_count"),
        roster_count.label("roster_count"),
        missing.label("missing"),
        has_comments.label("has_comments"),
    )


async def _list_sessions(
    conn: AsyncConnection, class_id: UUID, d: date, direction: str, limit: int
) -> list[dict[str, Any]] | None:
    """Upcoming (ascending) or past (descending) sessions. The split is by wall clock, not by
    date alone. Past rows carry attendance and pending-grade chips. None when empty."""
    cs = ClassSession
    past = direction == "past"
    if past:
        stmt = (
            select(*_SUMMARY, *_past_columns())
            .where(
                or_(
                    cs.session_date < d,
                    (cs.session_date == d) & (cs.scheduled_end_at < func.now()),
                )
            )
            .order_by(cs.session_date.desc(), cs.scheduled_start_at.desc())
        )
    else:
        stmt = (
            select(*_SUMMARY)
            .where(
                or_(
                    cs.session_date > d,
                    (cs.session_date == d) & (cs.scheduled_end_at >= func.now()),
                )
            )
            .order_by(cs.session_date.asc(), cs.scheduled_start_at.asc())
        )
    rows = await fetch_all(
        conn, stmt.where(cs.class_id == class_id, cs.deleted_at.is_(None)).limit(limit)
    )
    return [_session_summary(r, past=past) for r in rows] or None
