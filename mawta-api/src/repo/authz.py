"""Authorization lookups: which class a resource belongs to, and whether a teacher is
assigned to it.

RLS scopes every query to one school; no policy references a teacher. These
functions close that gap (see authz). Each resolver raises NotFound for an
id that does not exist *in this tenant*, which maps to 404: a wrong-tenant id is
indistinguishable from a made-up one.
"""

from datetime import date
from typing import LiteralString
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.abc import Params
from psycopg.rows import DictRow

from db import fetch_required


async def _exists(conn: AsyncConnection[DictRow], sql: LiteralString, params: Params) -> bool:
    row = await fetch_required(conn, sql, params)
    return bool(row["ok"])


async def teacher_teaches_class(
    conn: AsyncConnection[DictRow], class_id: UUID, teacher_id: UUID, today: date
) -> bool:
    """A live class_teachers row covering today (any role counts). `today` comes from the
    tenant's timezone, not the server clock."""
    return await _exists(
        conn,
        """
        select exists (
          select 1 from class_teachers ct
           where ct.class_id = %(class)s
             and ct.teacher_id = %(teacher)s
             and ct.deleted_at is null
             and ct.starts_on <= %(today)s
             and (ct.ends_on is null or ct.ends_on >= %(today)s)
        ) as ok
        """,
        {"class": class_id, "teacher": teacher_id, "today": today},
    )


async def teacher_teaches_subject(
    conn: AsyncConnection[DictRow], subject_id: UUID, teacher_id: UUID, today: date
) -> bool:
    """A live assignment to any class of the subject: the unit for curriculum authoring."""
    return await _exists(
        conn,
        """
        select exists (
          select 1
            from class_teachers ct
            join classes c on c.id = ct.class_id and c.deleted_at is null
            join courses co on co.id = c.course_id and co.deleted_at is null
           where ct.teacher_id = %(teacher)s
             and co.subject_id = %(subject)s
             and ct.deleted_at is null
             and ct.starts_on <= %(today)s
             and (ct.ends_on is null or ct.ends_on >= %(today)s)
        ) as ok
        """,
        {"teacher": teacher_id, "subject": subject_id, "today": today},
    )


async def student_on_class_roster(
    conn: AsyncConnection[DictRow], class_id: UUID, student_id: UUID, as_of: date
) -> bool:
    return await _exists(
        conn,
        """
        select exists (
          select 1
            from section_memberships sm
            join classes c on c.section_id = sm.section_id and c.id = %(class)s
                          and c.deleted_at is null
           where sm.student_id = %(student)s
             and sm.deleted_at is null
             and sm.joined_on <= %(d)s
             and (sm.left_on is null or sm.left_on > %(d)s)
        ) as ok
        """,
        {"class": class_id, "student": student_id, "d": as_of},
    )


async def class_id_for_session(conn: AsyncConnection[DictRow], session_id: UUID) -> UUID:
    row = await fetch_required(
        conn,
        "select class_id from class_sessions where id = %s and deleted_at is null",
        (session_id,),
    )
    return row["class_id"]


async def class_id_for_voice_note(conn: AsyncConnection[DictRow], voice_note_id: UUID) -> UUID:
    row = await fetch_required(
        conn,
        "select class_id from voice_notes where id = %s and deleted_at is null",
        (voice_note_id,),
    )
    return row["class_id"]


async def class_id_for_assessment(conn: AsyncConnection[DictRow], assessment_id: UUID) -> UUID:
    row = await fetch_required(
        conn,
        "select class_id from assessments where id = %s and deleted_at is null",
        (assessment_id,),
    )
    return row["class_id"]


async def class_id_for_score(conn: AsyncConnection[DictRow], score_id: UUID) -> UUID:
    """A superseded score still resolves: correcting one is the operation being authorized."""
    row = await fetch_required(
        conn, "select class_id from scores where id = %s and deleted_at is null", (score_id,)
    )
    return row["class_id"]


async def subject_id_for_competency(
    conn: AsyncConnection[DictRow], competency_id: UUID
) -> UUID | None:
    """None for a transversal competencia (no subject): shared across the school."""
    row = await fetch_required(
        conn,
        "select subject_id from competencies where id = %s and deleted_at is null",
        (competency_id,),
    )
    return row["subject_id"]


async def subject_id_for_criterion(
    conn: AsyncConnection[DictRow], criterion_id: UUID
) -> UUID | None:
    row = await fetch_required(
        conn,
        """
        select c.subject_id
          from evaluation_criteria ec
          join competencies c on c.id = ec.competency_id and c.deleted_at is null
         where ec.id = %s and ec.deleted_at is null
        """,
        (criterion_id,),
    )
    return row["subject_id"]


async def class_id_for_experience(conn: AsyncConnection[DictRow], experience_id: UUID) -> UUID:
    row = await fetch_required(
        conn,
        "select class_id from learning_experiences where id = %s and deleted_at is null",
        (experience_id,),
    )
    return row["class_id"]


async def class_id_for_evidence(conn: AsyncConnection[DictRow], evidence_id: UUID) -> UUID:
    row = await fetch_required(
        conn,
        """
        select le.class_id
          from planned_evidences pe
          join learning_experiences le on le.id = pe.experience_id and le.deleted_at is null
         where pe.id = %s and pe.deleted_at is null
        """,
        (evidence_id,),
    )
    return row["class_id"]


async def class_id_for_criterion(conn: AsyncConnection[DictRow], criterion_id: UUID) -> UUID | None:
    """The class of a criterio anchored to an experience; None for a global criterio
    (it belongs to an área, authorized through subject_id_for_criterion)."""
    row = await fetch_required(
        conn,
        """
        select le.class_id
          from evaluation_criteria ec
          left join learning_experiences le on le.id = ec.experience_id
         where ec.id = %s and ec.deleted_at is null
        """,
        (criterion_id,),
    )
    return row["class_id"]
