"""Authorization lookups: which class a resource belongs to, and whether a teacher is
assigned to it.

The database holds one school, so every row belongs to it; what remains to check is the
teacher. These functions do that (see authz). Each resolver raises NotFound for an id that
does not exist, which maps to 404.
"""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_required, scalar
from mawta_schema.tables import (
    Assessment,
    Class,
    ClassSession,
    ClassTeacher,
    Competency,
    Course,
    EvaluationCriterion,
    LearningExperience,
    PlannedEvidence,
    Score,
    SectionMembership,
    VoiceNote,
)


def _assigned_on(today: date) -> list[ColumnElement[bool]]:
    return [
        ClassTeacher.deleted_at.is_(None),
        ClassTeacher.starts_on <= today,
        or_(ClassTeacher.ends_on.is_(None), ClassTeacher.ends_on >= today),
    ]


async def teacher_teaches_class(
    conn: AsyncConnection, class_id: UUID, teacher_id: UUID, today: date
) -> bool:
    """A live class_teachers row covering today (any role counts). `today` comes from the
    school's timezone, not the server clock."""
    return await scalar(
        conn,
        select(
            exists().where(
                ClassTeacher.class_id == class_id,
                ClassTeacher.teacher_id == teacher_id,
                *_assigned_on(today),
            )
        ),
    )


async def teacher_teaches_subject(
    conn: AsyncConnection, subject_id: UUID, teacher_id: UUID, today: date
) -> bool:
    """A live assignment to any class of the subject: the unit for curriculum authoring."""
    return await scalar(
        conn,
        select(
            select(1)
            .select_from(ClassTeacher)
            .join(Class, (Class.id == ClassTeacher.class_id) & Class.deleted_at.is_(None))
            .join(Course, (Course.id == Class.course_id) & Course.deleted_at.is_(None))
            .where(
                ClassTeacher.teacher_id == teacher_id,
                Course.subject_id == subject_id,
                *_assigned_on(today),
            )
            .exists()
        ),
    )


async def student_on_class_roster(
    conn: AsyncConnection, class_id: UUID, student_id: UUID, as_of: date
) -> bool:
    return await scalar(
        conn,
        select(
            select(1)
            .select_from(SectionMembership)
            .join(
                Class,
                (Class.section_id == SectionMembership.section_id)
                & (Class.id == class_id)
                & Class.deleted_at.is_(None),
            )
            .where(
                SectionMembership.student_id == student_id,
                SectionMembership.deleted_at.is_(None),
                SectionMembership.joined_on <= as_of,
                or_(SectionMembership.left_on.is_(None), SectionMembership.left_on > as_of),
            )
            .exists()
        ),
    )


async def _one(conn: AsyncConnection, column: Any, *where: ColumnElement[bool]) -> Any:
    row = await fetch_required(conn, select(column.label("v")).where(*where))
    return row["v"]


async def class_id_for_session(conn: AsyncConnection, session_id: UUID) -> UUID:
    return await _one(
        conn,
        ClassSession.class_id,
        ClassSession.id == session_id,
        ClassSession.deleted_at.is_(None),
    )


async def class_id_for_voice_note(conn: AsyncConnection, voice_note_id: UUID) -> UUID:
    return await _one(
        conn, VoiceNote.class_id, VoiceNote.id == voice_note_id, VoiceNote.deleted_at.is_(None)
    )


async def class_id_for_assessment(conn: AsyncConnection, assessment_id: UUID) -> UUID:
    return await _one(
        conn, Assessment.class_id, Assessment.id == assessment_id, Assessment.deleted_at.is_(None)
    )


async def class_id_for_score(conn: AsyncConnection, score_id: UUID) -> UUID:
    """A superseded score still resolves: correcting one is the operation being authorized."""
    return await _one(conn, Score.class_id, Score.id == score_id, Score.deleted_at.is_(None))


async def subject_id_for_competency(conn: AsyncConnection, competency_id: UUID) -> UUID | None:
    """None for a transversal competencia (no subject): shared across the school."""
    return await _one(
        conn, Competency.subject_id, Competency.id == competency_id, Competency.deleted_at.is_(None)
    )


async def subject_id_for_criterion(conn: AsyncConnection, criterion_id: UUID) -> UUID | None:
    row = await fetch_required(
        conn,
        select(Competency.subject_id)
        .select_from(EvaluationCriterion)
        .join(
            Competency,
            (Competency.id == EvaluationCriterion.competency_id) & Competency.deleted_at.is_(None),
        )
        .where(EvaluationCriterion.id == criterion_id, EvaluationCriterion.deleted_at.is_(None)),
    )
    return row["subject_id"]


async def class_id_for_experience(conn: AsyncConnection, experience_id: UUID) -> UUID:
    return await _one(
        conn,
        LearningExperience.class_id,
        LearningExperience.id == experience_id,
        LearningExperience.deleted_at.is_(None),
    )


async def class_id_for_evidence(conn: AsyncConnection, evidence_id: UUID) -> UUID:
    row = await fetch_required(
        conn,
        select(LearningExperience.class_id)
        .select_from(PlannedEvidence)
        .join(
            LearningExperience,
            (LearningExperience.id == PlannedEvidence.experience_id)
            & LearningExperience.deleted_at.is_(None),
        )
        .where(PlannedEvidence.id == evidence_id, PlannedEvidence.deleted_at.is_(None)),
    )
    return row["class_id"]


async def class_id_for_criterion(conn: AsyncConnection, criterion_id: UUID) -> UUID | None:
    """The class of a criterio anchored to an experience; None for a global criterio
    (it belongs to an área, authorized through subject_id_for_criterion)."""
    row = await fetch_required(
        conn,
        select(LearningExperience.class_id)
        .select_from(EvaluationCriterion)
        .outerjoin(LearningExperience, LearningExperience.id == EvaluationCriterion.experience_id)
        .where(EvaluationCriterion.id == criterion_id, EvaluationCriterion.deleted_at.is_(None)),
    )
    return row["class_id"]
