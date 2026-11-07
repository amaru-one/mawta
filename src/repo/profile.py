"""The teacher's profile screen."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Date, cast, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_all, fetch_required, scalar
from mawta_schema.tables import (
    Assessment,
    Class,
    ClassSchedule,
    ClassSession,
    ClassTeacher,
    GradeLevel,
    School,
    Section,
    SectionMembership,
    Teacher,
    VoiceNote,
)
from repo.roster import roster_as_of


def _midnight_utc(value: date | None) -> str | None:
    """A date column in the API's timestamp form (midnight UTC)."""
    return f"{value.isoformat()}T00:00:00Z" if value is not None else None


def _schedule_live(today: date):
    return (
        ClassSchedule.effective_from <= today,
        or_(ClassSchedule.effective_to.is_(None), ClassSchedule.effective_to > today),
        ClassSchedule.deleted_at.is_(None),
    )


async def get_profile(
    conn: AsyncConnection, teacher_id: UUID, term: dict[str, Any], today: date
) -> dict[str, Any]:
    head = await fetch_required(
        conn,
        select(
            Teacher.display_name,
            Teacher.title,
            Teacher.hired_on,
            School.name.label("school_name"),
            School.city.label("school_city"),
        )
        .join_from(Teacher, School, School.singleton.is_(True))
        .where(Teacher.id == teacher_id),
    )
    resp: dict[str, Any] = {
        "display_name": head["display_name"],
        "title": head["title"],
        "hired_on": _midnight_utc(head["hired_on"]),
        "school_name": head["school_name"],
        "school_city": head["school_city"],
        "top_stats": {"classes": 0, "students": 0, "weekly_hours": 0.0},
        "activity": {
            "clases_dictadas": 0,
            "asistencias_registradas": 0,
            "asistencias_esperadas": 0,
            "notas_de_voz": 0,
            "evaluaciones": 0,
        },
        "classes_by_grade": None,
    }

    class_rows = await fetch_all(
        conn,
        select(
            Class.id,
            Class.name,
            Section.id.label("section_id"),
            GradeLevel.long_label.label("grade_label"),
            GradeLevel.ordinal,
        )
        .distinct()
        .select_from(ClassTeacher)
        .join(
            Class,
            (Class.id == ClassTeacher.class_id)
            & Class.deleted_at.is_(None)
            & (Class.status == "active"),
        )
        .join(Section, Section.id == Class.section_id)
        .join(GradeLevel, GradeLevel.id == Section.grade_level_id)
        .where(
            ClassTeacher.teacher_id == teacher_id,
            ClassTeacher.starts_on <= today,
            or_(ClassTeacher.ends_on.is_(None), ClassTeacher.ends_on >= today),
            ClassTeacher.deleted_at.is_(None),
        )
        .order_by(GradeLevel.ordinal, Class.name),
    )
    if not class_rows:
        return resp

    class_ids = [r["id"] for r in class_rows]
    section_ids = [r["section_id"] for r in class_rows]
    resp["top_stats"]["classes"] = len(class_rows)

    resp["top_stats"]["students"] = await scalar(
        conn,
        select(func.count(SectionMembership.student_id.distinct())).where(
            SectionMembership.section_id.in_(section_ids),
            SectionMembership.joined_on <= today,
            or_(SectionMembership.left_on.is_(None), SectionMembership.left_on > today),
            SectionMembership.deleted_at.is_(None),
        ),
    )

    hours = func.sum(extract("epoch", ClassSchedule.ends_at - ClassSchedule.starts_at) / 3600.0)
    resp["top_stats"]["weekly_hours"] = float(
        await scalar(
            conn,
            select(func.coalesce(hours, 0)).where(
                ClassSchedule.class_id.in_(class_ids), *_schedule_live(today)
            ),
        )
    )

    if term["id"] is not None:
        sessions = await fetch_required(
            conn,
            select(
                func.count().label("taught"),
                func.count()
                .filter(ClassSession.attendance_taken_at.is_not(None))
                .label("registered"),
            ).where(
                ClassSession.class_id.in_(class_ids),
                ClassSession.term_id == term["id"],
                ClassSession.status == "completed",
                ClassSession.deleted_at.is_(None),
            ),
        )
        activity = resp["activity"]
        activity["clases_dictadas"] = sessions["taught"]
        activity["asistencias_registradas"] = sessions["registered"]
        activity["asistencias_esperadas"] = sessions["taught"]
        activity["notas_de_voz"] = await scalar(
            conn,
            select(func.count()).where(
                VoiceNote.teacher_id == teacher_id,
                cast(VoiceNote.recorded_at, Date).between(term["starts_on"], term["ends_on"]),
                VoiceNote.deleted_at.is_(None),
            ),
        )
        activity["evaluaciones"] = await scalar(
            conn,
            select(func.count()).where(
                Assessment.created_by_id == teacher_id,
                Assessment.term_id == term["id"],
                Assessment.deleted_at.is_(None),
            ),
        )

    groups: dict[str, dict[str, Any]] = {}
    for cr in class_rows:
        roster = await roster_as_of(conn, cr["id"], today)
        slots = await scalar(
            conn,
            select(func.count()).where(ClassSchedule.class_id == cr["id"], *_schedule_live(today)),
        )
        group = groups.setdefault(
            cr["grade_label"], {"grade_label": cr["grade_label"], "classes": []}
        )
        group["classes"].append(
            {
                "class_id": cr["id"],
                "name": cr["name"],
                "roster_count": len(roster),
                "slots_per_week": slots,
            }
        )
    resp["classes_by_grade"] = list(groups.values())
    return resp
