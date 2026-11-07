"""Evidence (assessments) and scores.

A piece of evidence carries no weight: under RVM 094-2020 a mark informs the teacher's
judgement of the criterios and never feeds a final grade arithmetically.
"""

from typing import Any, SupportsFloat
from uuid import UUID

from sqlalchemy import DateTime, cast, exists, func, insert, literal, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

import domain
from db import fetch_one, fetch_required, scalar
from errors import AppError
from mawta_schema.tables import (
    Assessment,
    AssessmentCriterion,
    Class,
    Competency,
    Course,
    EvaluationCriterion,
    GradeScale,
    GradeScaleLevel,
    LearningExperience,
    Score,
    SectionMembership,
)


def _bad(code: str, message: str) -> AppError:
    return AppError(400, code, message)


async def create_assessment(
    conn: AsyncConnection,
    *,
    class_id: UUID,
    term_id: UUID,
    teacher_id: UUID,
    student_id: UUID | None,
    title: str,
    kind: str,
    value_scale: str,
    max_score: float | None,
    due_at: str | None,
    criterion_ids: list[UUID],
) -> UUID:
    """File one piece of evidence. student_id None means the whole class; set, it is
    evidence for that student alone. At least one criterio is required: that is how the
    evidence reaches a competencia."""
    if not criterion_ids:
        raise _bad(
            "criteria_required",
            "an evidence needs at least one criterio: that is how it reaches a competencia",
        )
    if student_id is not None:
        # The student must be on this class's roster, or a teacher could file evidence against
        # a student from another section by id.
        on_roster = await scalar(
            conn,
            select(
                select(1)
                .select_from(Class)
                .join(SectionMembership, SectionMembership.section_id == Class.section_id)
                .where(
                    Class.id == class_id,
                    SectionMembership.student_id == student_id,
                    SectionMembership.joined_on <= func.current_date(),
                    or_(
                        SectionMembership.left_on.is_(None),
                        SectionMembership.left_on > func.current_date(),
                    ),
                    SectionMembership.deleted_at.is_(None),
                    Class.deleted_at.is_(None),
                )
                .exists()
            ),
        )
        if not on_roster:
            raise _bad("student_not_in_class", "that student is not on this class's roster")

    assessment_id = await scalar(
        conn,
        insert(Assessment)
        .values(
            class_id=class_id,
            term_id=term_id,
            student_id=student_id,
            title=title,
            kind=kind,
            value_scale=value_scale,
            max_score=max_score,
            # Postgres parses the client's timestamp, as it always has.
            due_at=cast(due_at, DateTime(timezone=True)) if due_at is not None else None,
            status="published",
            published_at=func.now(),
            created_by_id=teacher_id,
        )
        .returning(Assessment.id),
    )
    await _link_assessment_criteria(conn, class_id, term_id, assessment_id, criterion_ids)
    return assessment_id


async def _link_assessment_criteria(
    conn: AsyncConnection,
    class_id: UUID,
    term_id: UUID,
    assessment_id: UUID,
    criterion_ids: list[UUID],
) -> None:
    """Record which criterios an assessment evidences. Every criterio must belong to a
    competencia of the class's área; a criterio of an experiencia must also be one
    list_evidence_criteria offers (accepted, of a planned experiencia of this class and
    term), or a teacher could tag evidence with another class's criterio or a draft."""
    ec = EvaluationCriterion
    planned_here = exists().where(
        LearningExperience.id == ec.experience_id,
        LearningExperience.class_id == class_id,
        LearningExperience.term_id == term_id,
        LearningExperience.status == "planificada",
        LearningExperience.deleted_at.is_(None),
    )
    valid = await scalar(
        conn,
        select(func.count())
        .select_from(ec)
        .join(Competency, Competency.id == ec.competency_id)
        .join(Course, Course.subject_id == Competency.subject_id)
        .join(Class, Class.course_id == Course.id)
        .where(
            Class.id == class_id,
            ec.id.in_(criterion_ids),
            ec.deleted_at.is_(None),
            Competency.deleted_at.is_(None),
            Class.deleted_at.is_(None),
            or_(ec.experience_id.is_(None), ec.accepted_at.is_not(None) & planned_here),
        ),
    )
    if valid != len(criterion_ids):
        raise _bad(
            "criterion_not_in_class",
            "one of those criterios does not belong to this class's área or to a planned"
            " experiencia of this class and period",
        )
    await conn.execute(
        insert(AssessmentCriterion).values(
            [{"assessment_id": assessment_id, "criterion_id": c} for c in criterion_ids]
        )
    )


async def delete_assessment(conn: AsyncConnection, assessment_id: UUID) -> dict[str, Any]:
    """Soft-delete a piece of evidence; its scores stay in the student's history.
    Returns {class_id, term_id, student_id} for the audit event."""
    row = await fetch_one(
        conn,
        update(Assessment)
        .where(Assessment.id == assessment_id, Assessment.deleted_at.is_(None))
        .values(deleted_at=func.now())
        .returning(Assessment.class_id, Assessment.term_id, Assessment.student_id),
    )
    if row is None:
        raise AppError(404, "assessment_not_found", "that evidence no longer exists")
    return dict(row)


def _check_value(
    value_scale: str, max_score: float | None, status: str, raw: float | None, level: str | None
) -> None:
    """Reject a value that does not fit the evidence's scale before it reaches the database,
    so the teacher gets a message instead of a constraint name."""
    if status != domain.SCORE_GRADED:
        if raw is not None or level is not None:
            raise _bad("value_not_allowed", "a status other than graded carries no value")
        return
    if value_scale == domain.VALUE_SCALE_NUMERIC:
        if level is not None:
            raise _bad("level_on_numeric", "this evidence is valued with a mark, not a level")
        if raw is None:
            raise _bad("value_required", "a graded score needs a mark")
        if raw < 0 or (max_score is not None and raw > max_score):
            raise _bad(
                "mark_out_of_range",
                "the mark must be between 0 and the maximum of this evidence",
            )
    elif value_scale == domain.VALUE_SCALE_ORDINAL:
        if raw is not None:
            raise _bad("mark_on_ordinal", "this evidence is valued with a level, not a mark")
        if level is None:
            raise _bad("value_required", "a graded score needs a level")


async def _level_id(conn: AsyncConnection, code: str) -> UUID:
    """Resolve an AD/A/B/C code to the school's ordinal scale level."""
    row = await fetch_one(
        conn,
        select(GradeScaleLevel.id)
        .join(GradeScale, GradeScale.id == GradeScaleLevel.scale_id)
        .where(
            GradeScale.kind == "ordinal",
            GradeScaleLevel.code == code,
            GradeScaleLevel.deleted_at.is_(None),
            GradeScale.deleted_at.is_(None),
        ),
    )
    if row is None:
        raise _bad("invalid_level", "level must be one of AD, A, B, C")
    return row["id"]


async def _assessment_scale(conn: AsyncConnection, assessment_id: UUID) -> tuple[str, float | None]:
    row = await fetch_one(
        conn,
        select(Assessment.value_scale, Assessment.max_score).where(
            Assessment.id == assessment_id, Assessment.deleted_at.is_(None)
        ),
    )
    if row is None:
        raise AppError(404, "assessment_not_found", "that evidence no longer exists")
    return row["value_scale"], _float(row["max_score"])


def _float(value: SupportsFloat | None) -> float | None:
    return float(value) if value is not None else None


def _insert_score(
    assessment_id: UUID,
    student_id: UUID,
    status: str,
    raw_value: float | None,
    scale_level: UUID | None,
    teacher_id: UUID,
    supersedes: UUID | None = None,
):
    """A scores row whose max_value is the assessment's maximum, so it is always the
    denominator the score was recorded out of, even if the assessment's own max changes
    later. class_id and term_id are filled by the sync_denormalised trigger."""
    columns = {
        "assessment_id": Assessment.id,
        "student_id": literal(student_id, Score.student_id.type),
        "status": literal(status, Score.status.type),
        "raw_value": literal(raw_value, Score.raw_value.type),
        "max_value": Assessment.max_score,
        "scale_level_id": literal(scale_level, Score.scale_level_id.type),
        "source": literal("manual", Score.source.type),
        "recorded_by_id": literal(teacher_id, Score.recorded_by_id.type),
    }
    if supersedes is not None:
        columns["supersedes_id"] = literal(supersedes, Score.supersedes_id.type)
    return (
        insert(Score)
        .from_select(list(columns), select(*columns.values()).where(Assessment.id == assessment_id))
        .returning(Score.id, Score.class_id, Score.term_id)
    )


async def create_score(
    conn: AsyncConnection,
    assessment_id: UUID,
    student_id: UUID,
    teacher_id: UUID,
    status: str,
    raw_value: float | None,
    level: str | None,
) -> tuple[UUID, UUID, UUID]:
    """Record the first valuation of a student on an evidence: (id, class_id, term_id)."""
    value_scale, max_score = await _assessment_scale(conn, assessment_id)
    _check_value(value_scale, max_score, status, raw_value, level)
    scale_level = await _level_id(conn, level) if level is not None else None
    row = await fetch_required(
        conn, _insert_score(assessment_id, student_id, status, raw_value, scale_level, teacher_id)
    )
    return row["id"], row["class_id"], row["term_id"]


async def correct_score(
    conn: AsyncConnection,
    score_id: UUID,
    teacher_id: UUID,
    raw_value: float | None,
    level: str | None,
    status: str | None,
) -> tuple[UUID, UUID, UUID, UUID]:
    """The supersede protocol: stamp superseded_at on the live row first, then insert the
    replacement with supersedes_id set, in that order and one transaction, because
    scores_live_key is a partial unique index and cannot be deferred. A correction that
    names nothing inherits the old value, except that a status other than graded carries no
    value. Returns (new_score_id, student_id, class_id, term_id)."""
    old = await fetch_one(
        conn,
        select(
            Score.assessment_id,
            Score.student_id,
            Score.status,
            Score.raw_value,
            GradeScaleLevel.code.label("level"),
        )
        .outerjoin(GradeScaleLevel, GradeScaleLevel.id == Score.scale_level_id)
        .where(Score.id == score_id, Score.superseded_at.is_(None), Score.deleted_at.is_(None)),
    )
    if old is None:
        raise AppError(409, "already_superseded", "score already superseded; reload and try again")
    value_scale, max_score = await _assessment_scale(conn, old["assessment_id"])

    new_status = status if status is not None else old["status"]
    new_raw = raw_value if raw_value is not None else _float(old["raw_value"])
    new_level = level if level is not None else old["level"]
    # not_submitted and its siblings carry no value; keeping the old mark would leave a number
    # on a row that says nothing was handed in.
    if new_status != domain.SCORE_GRADED:
        new_raw, new_level = None, None
    _check_value(value_scale, max_score, new_status, new_raw, new_level)
    scale_level = await _level_id(conn, new_level) if new_level is not None else None

    await conn.execute(update(Score).where(Score.id == score_id).values(superseded_at=func.now()))
    row = await fetch_required(
        conn,
        _insert_score(
            old["assessment_id"],
            old["student_id"],
            new_status,
            new_raw,
            scale_level,
            teacher_id,
            supersedes=score_id,
        ),
    )
    return row["id"], old["student_id"], row["class_id"], row["term_id"]
