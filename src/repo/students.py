"""The class list and one student's evidence."""

from datetime import date
from typing import Any, SupportsFloat
from uuid import UUID

from sqlalchemy import ColumnElement, Text, false, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_all
from mawta_schema.tables import (
    Assessment,
    AssessmentCriterion,
    Class,
    CompetencyTermLevel,
    EvaluationCriterion,
    GradeScaleLevel,
    Score,
    SectionMembership,
    Student,
)


def _for_competency(competency_id: UUID | None) -> list[ColumnElement[bool]]:
    """Narrow assessments to those tagged with a criterio of the competencia, when there is one."""
    if competency_id is None:
        return []
    return [
        select(1)
        .select_from(AssessmentCriterion)
        .join(EvaluationCriterion, EvaluationCriterion.id == AssessmentCriterion.criterion_id)
        .where(
            AssessmentCriterion.assessment_id == Assessment.id,
            AssessmentCriterion.deleted_at.is_(None),
            EvaluationCriterion.competency_id == competency_id,
        )
        .exists()
    ]


def _published(class_id: UUID, term_id: UUID) -> list[ColumnElement[bool]]:
    return [
        Assessment.class_id == class_id,
        Assessment.term_id == term_id,
        Assessment.status == "published",
        Assessment.deleted_at.is_(None),
    ]


async def list_class_students(
    conn: AsyncConnection,
    class_id: UUID,
    competency_id: UUID | None,
    term_id: UUID,
    as_of: date,
) -> list[dict[str, Any]]:
    """The class roster as of today with each student's level in one competencia.

    Without competency_id the list is just the roster: no level, and the evidence count
    covers the whole área. level is None when the teacher has not asserted one this period:
    a real state under RVM 048-2024 5.1.2.2, never rendered as C or zero.
    """
    full_name = (
        Student.paternal_surname
        + func.coalesce(literal(" ", Text) + Student.maternal_surname, "")
        + ", "
        + func.coalesce(Student.preferred_name, Student.given_name)
    )
    evidence_count = (
        select(func.count())
        .select_from(Assessment)
        .where(
            *_published(class_id, term_id),
            or_(Assessment.student_id.is_(None), Assessment.student_id == Student.id),
            *_for_competency(competency_id),
        )
        .scalar_subquery()
    )
    level_join = (
        (CompetencyTermLevel.student_id == Student.id)
        & (
            CompetencyTermLevel.competency_id == competency_id
            if competency_id is not None
            else false()
        )
        & (CompetencyTermLevel.term_id == term_id)
        & CompetencyTermLevel.superseded_at.is_(None)
        & CompetencyTermLevel.deleted_at.is_(None)
    )
    rows = await fetch_all(
        conn,
        select(
            Student.id.label("student_id"),
            full_name.label("full_name"),
            GradeScaleLevel.code.label("level"),
            evidence_count.label("evidence_count"),
        )
        .select_from(SectionMembership)
        .join(Class, (Class.section_id == SectionMembership.section_id) & (Class.id == class_id))
        .join(Student, (Student.id == SectionMembership.student_id) & Student.deleted_at.is_(None))
        .outerjoin(CompetencyTermLevel, level_join)
        .outerjoin(GradeScaleLevel, GradeScaleLevel.id == CompetencyTermLevel.scale_level_id)
        .where(
            SectionMembership.joined_on <= as_of,
            or_(SectionMembership.left_on.is_(None), SectionMembership.left_on > as_of),
            SectionMembership.deleted_at.is_(None),
            Class.deleted_at.is_(None),
        )
        .order_by(
            Student.paternal_surname,
            Student.maternal_surname.asc().nulls_first(),
            Student.given_name,
        ),
    )
    return [dict(r) for r in rows]


async def list_student_evidence(
    conn: AsyncConnection,
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID | None,
    term_id: UUID,
) -> list[dict[str, Any]]:
    """The period's evidencia for one student, narrowed to the competencia being judged
    through assessment_criteria, each piece carrying the student's valuation. Nothing here is
    aggregated: the list is material for a judgement the teacher makes."""
    own_or_class = or_(Assessment.student_id.is_(None), Assessment.student_id == student_id)
    rows = await fetch_all(
        conn,
        select(
            Assessment.id.label("assessment_id"),
            Assessment.title,
            Assessment.kind,
            Assessment.value_scale,
            Assessment.max_score,
            Assessment.due_at,
            Assessment.student_id.is_not(None).label("is_personal"),
            Score.id.label("score_id"),
            Score.status,
            Score.raw_value,
            GradeScaleLevel.code.label("level"),
        )
        .outerjoin(
            Score,
            (Score.assessment_id == Assessment.id)
            & (Score.student_id == student_id)
            & Score.superseded_at.is_(None)
            & Score.deleted_at.is_(None),
        )
        .outerjoin(GradeScaleLevel, GradeScaleLevel.id == Score.scale_level_id)
        .where(*_published(class_id, term_id), own_or_class, *_for_competency(competency_id))
        .order_by(Assessment.due_at.asc().nulls_last(), Assessment.title),
    )
    entries: dict[UUID, dict[str, Any]] = {}
    for r in rows:
        score = None
        max_score = _float(r["max_score"])
        if r["score_id"] is not None:
            raw = _float(r["raw_value"])
            pct = raw / max_score * 100 if raw is not None and max_score and max_score > 0 else None
            score = {
                "score_id": r["score_id"],
                "status": r["status"],
                "raw_value": raw,
                "percentage": pct,
                "level": r["level"],
            }
        entries[r["assessment_id"]] = {
            "assessment_id": r["assessment_id"],
            "title": r["title"],
            "kind": r["kind"],
            "value_scale": r["value_scale"],
            "max_score": max_score,
            "due_at": r["due_at"],
            "is_personal": r["is_personal"],
            "criteria": [],
            "score": score,
        }

    # The criterio tags, read separately: one assessment carries several, and joining them
    # above would multiply the rows.
    crit_rows = await fetch_all(
        conn,
        select(
            AssessmentCriterion.assessment_id,
            EvaluationCriterion.id.label("criterion_id"),
            EvaluationCriterion.code,
            EvaluationCriterion.description,
        )
        .join(Assessment, Assessment.id == AssessmentCriterion.assessment_id)
        .join(EvaluationCriterion, EvaluationCriterion.id == AssessmentCriterion.criterion_id)
        .where(
            *_published(class_id, term_id),
            own_or_class,
            AssessmentCriterion.deleted_at.is_(None),
            EvaluationCriterion.deleted_at.is_(None),
        )
        .order_by(EvaluationCriterion.sort_order, EvaluationCriterion.code),
    )
    for c in crit_rows:
        entry = entries.get(c["assessment_id"])
        if entry is not None:
            entry["criteria"].append(
                {
                    "criterion_id": c["criterion_id"],
                    "code": c["code"],
                    "description": c["description"],
                }
            )
    return list(entries.values())


def _float(value: SupportsFloat | None) -> float | None:
    return float(value) if value is not None else None
