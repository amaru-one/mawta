"""Niveles de logro and conclusiones descriptivas."""

from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, false, func, insert, literal, select, update
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.orm import aliased

import domain
from db import fetch_all, fetch_one, fetch_required, scalar
from errors import AppError
from mawta_schema.tables import (
    AgentGeneration,
    AssessmentCriterion,
    Class,
    Competency,
    CompetencyTermLevel,
    Course,
    DescriptiveConclusion,
    EvaluationCriterion,
    GradeLevel,
    GradeScale,
    GradeScaleLevel,
    LearningStandard,
    Score,
    StandardLevelMapping,
    Student,
    Term,
)


def classify_conclusion_requirement(
    inclusion_support: bool, stage: str, cycle: str, level_code: str | None, consecutive_c: bool
) -> str:
    """Why a conclusión descriptiva is (or isn't) mandatory, per the grade-level-dependent
    obligatoriedad: inclusion support is mandatory every period regardless of level or grade;
    Inicial Ciclo I requires one for every competencia regardless of level; otherwise the level
    itself decides by nivel educativo (C in Secundaria/Primaria/Inicial Ciclo II, B in
    Primaria/Inicial Ciclo II, A only in Inicial Ciclo II). C also carries the stronger
    consecutive_c classification when the competency was C in the immediately preceding period
    too (RVM 048-2024, 5.1.1.3 p.3)."""
    if inclusion_support:
        return domain.CONCLUSION_INCLUSION_SUPPORT
    if stage == domain.STAGE_INICIAL and cycle == domain.CYCLE_I:
        return domain.CONCLUSION_CYCLE_I_MANDATORY
    if level_code is None:
        return domain.CONCLUSION_OPTIONAL
    inicial_cycle_ii = stage == domain.STAGE_INICIAL and cycle == domain.CYCLE_II
    if level_code == domain.LEVEL_C:
        return domain.CONCLUSION_CONSECUTIVE_C if consecutive_c else domain.CONCLUSION_LEVEL_C
    if level_code == domain.LEVEL_B and (stage == domain.STAGE_PRIMARIA or inicial_cycle_ii):
        return domain.CONCLUSION_LEVEL_B
    if level_code == domain.LEVEL_A and inicial_cycle_ii:
        return domain.CONCLUSION_LEVEL_A
    return domain.CONCLUSION_OPTIONAL


async def stage_and_cycle(conn: AsyncConnection, class_id: UUID) -> tuple[str, str]:
    row = await fetch_required(
        conn,
        select(GradeLevel.stage, func.coalesce(GradeLevel.cycle, "").label("cycle"))
        .select_from(Class)
        .join(Course, Course.id == Class.course_id)
        .join(GradeLevel, GradeLevel.id == Course.grade_level_id)
        .where(Class.id == class_id),
    )
    return row["stage"], row["cycle"]


async def expected_standards(
    conn: AsyncConnection, cycle: str, competency_ids: list[UUID]
) -> dict[UUID, dict[str, Any]]:
    """The learning standard each competency expects at the end of `cycle` (CNEB: the level is
    judged against the standard of the cycle's expected level), keyed by competency id. A
    competency without a standard at that level is left out."""
    if not cycle or not competency_ids:
        return {}
    rows = await fetch_all(
        conn,
        select(
            LearningStandard.competency_id, LearningStandard.level, LearningStandard.official_text
        )
        .select_from(StandardLevelMapping)
        .join(LearningStandard, LearningStandard.level == StandardLevelMapping.expected_level)
        .where(
            StandardLevelMapping.modality == "ebr",
            StandardLevelMapping.cycle == cycle,
            StandardLevelMapping.deleted_at.is_(None),
            LearningStandard.competency_id.in_(competency_ids),
            LearningStandard.deleted_at.is_(None),
        ),
    )
    return {
        r["competency_id"]: {"level": r["level"], "cycle": cycle, "text": r["official_text"]}
        for r in rows
    }


def _live_level():
    ctl = CompetencyTermLevel
    return (ctl.superseded_at.is_(None), ctl.deleted_at.is_(None))


async def list_class_competency_levels(
    conn: AsyncConnection, class_id: UUID, student_id: UUID, term_id: UUID
) -> list[dict[str, Any]] | None:
    """Every competency of the class's subject with this student's asserted level and
    conclusion for the term. There is deliberately no suggested level."""
    stage, cycle = await stage_and_cycle(conn, class_id)
    ctl, gsl = CompetencyTermLevel, GradeScaleLevel
    subject = (
        select(Course.subject_id)
        .select_from(Class)
        .join(Course, Course.id == Class.course_id)
        .where(Class.id == class_id)
        .scalar_subquery()
    )
    lvl = (
        select(
            ctl.competency_id,
            ctl.scale_level_id,
            ctl.asserted_at,
            ctl.term_id,
            gsl.code.label("level_code"),
        )
        .join(gsl, gsl.id == ctl.scale_level_id)
        .where(ctl.student_id == student_id, ctl.term_id == term_id, *_live_level())
        .cte("lvl")
    )
    # Was this competency at C in the immediately preceding period (same academic year,
    # sequence - 1)?
    pt, t = aliased(Term, name="pt"), aliased(Term, name="t")
    prev_c = (
        select(ctl.competency_id)
        .join(pt, pt.id == ctl.term_id)
        .join(t, t.id == term_id)
        .join(gsl, gsl.id == ctl.scale_level_id)
        .where(
            ctl.student_id == student_id,
            pt.academic_year_id == t.academic_year_id,
            pt.sequence == t.sequence - 1,
            gsl.code == domain.LEVEL_C,
            *_live_level(),
        )
        .cte("prev_c")
    )
    dc = DescriptiveConclusion
    concl = (
        select(dc.competency_id, dc.body, dc.status, dc.authored_at)
        .where(
            dc.student_id == student_id,
            dc.term_id == term_id,
            dc.superseded_at.is_(None),
            dc.deleted_at.is_(None),
        )
        .cte("concl")
    )
    # Last change to any score of the student in this term, per competency. Scores are
    # append-only: a new mark, a correction and a removal each touch created_at,
    # superseded_at or deleted_at. greatest() ignores nulls.
    ec = EvaluationCriterion
    grades = (
        select(
            ec.competency_id,
            func.max(func.greatest(Score.created_at, Score.superseded_at, Score.deleted_at)).label(
                "last_change"
            ),
        )
        .select_from(Score)
        .join(
            AssessmentCriterion,
            (AssessmentCriterion.assessment_id == Score.assessment_id)
            & AssessmentCriterion.deleted_at.is_(None),
        )
        .join(ec, ec.id == AssessmentCriterion.criterion_id)
        .where(Score.student_id == student_id, Score.term_id == term_id)
        .group_by(ec.competency_id)
        .cte("grades")
    )
    rows = await fetch_all(
        conn,
        select(
            Competency.id.label("competency_id"),
            Competency.code,
            Competency.name,
            Competency.kind,
            Competency.subject_id,
            lvl.c.level_code.label("level"),
            lvl.c.scale_level_id.label("level_id"),
            func.to_char(
                func.timezone("UTC", lvl.c.asserted_at), 'YYYY-MM-DD"T"HH24:MI:SS"Z"'
            ).label("asserted_at"),
            Student.inclusion_support,
            prev_c.c.competency_id.is_not(None).label("consecutive_c"),
            concl.c.body.label("conclusion_body"),
            concl.c.status.label("conclusion_status"),
            func.coalesce(grades.c.last_change > concl.c.authored_at, false()).label(
                "grades_changed"
            ),
        )
        .select_from(Competency)
        .join(Student, Student.id == student_id)
        .outerjoin(lvl, lvl.c.competency_id == Competency.id)
        .outerjoin(prev_c, prev_c.c.competency_id == Competency.id)
        .outerjoin(concl, concl.c.competency_id == Competency.id)
        .outerjoin(grades, grades.c.competency_id == Competency.id)
        .where(
            Competency.subject_id == subject,
            Competency.is_active,
            Competency.deleted_at.is_(None),
        )
        .order_by(Competency.sort_order, Competency.code),
    )
    standards = await expected_standards(conn, cycle, [r["competency_id"] for r in rows])
    out: list[dict[str, Any]] = []
    for r in rows:
        requirement = classify_conclusion_requirement(
            r["inclusion_support"], stage, cycle, r["level"], r["consecutive_c"]
        )
        out.append(
            {
                "competency_id": r["competency_id"],
                "code": r["code"],
                "name": r["name"],
                "kind": r["kind"],
                "subject_id": r["subject_id"],
                "level": r["level"],
                "level_id": r["level_id"],
                "asserted_at": r["asserted_at"],
                "conclusion_required": requirement != domain.CONCLUSION_OPTIONAL,
                "conclusion_requirement": requirement,
                "conclusion_body": r["conclusion_body"],
                "conclusion_status": r["conclusion_status"],
                "grades_changed": r["grades_changed"],
                "standard": standards.get(r["competency_id"]),
            }
        )
    return out or None


async def _ordinal_level_id(conn: AsyncConnection, level_code: str) -> UUID | None:
    row = await fetch_one(
        conn,
        select(GradeScaleLevel.id)
        .join(GradeScale, GradeScale.id == GradeScaleLevel.scale_id)
        .where(
            GradeScale.kind == "ordinal",
            GradeScaleLevel.code == level_code,
            GradeScaleLevel.deleted_at.is_(None),
            GradeScale.deleted_at.is_(None),
        )
        .limit(1),
    )
    return row["id"] if row else None


def _typed(column: Any, value: Any) -> Any:
    """A bound value carrying its column's type, for INSERT ... SELECT lists."""
    return literal(value, column.type)


async def assert_competency_level(
    conn: AsyncConnection,
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID,
    term_id: UUID,
    teacher_id: UUID,
    level_code: str,
    note: str | None,
) -> UUID:
    """Record a teacher's nivel de logro for one competency in one period, superseding any level
    already on record. The only way an official level is ever written; nothing is derived into
    it: under RVM 094-2020 it is the teacher's judgement of the period's evidence."""
    level_id = await _ordinal_level_id(conn, level_code)
    if level_id is None:
        raise AppError(400, "unknown_level", "level must be one of AD, A, B or C")

    ctl = CompetencyTermLevel
    old = await fetch_one(
        conn,
        update(ctl)
        .where(
            ctl.student_id == student_id,
            ctl.competency_id == competency_id,
            ctl.term_id == term_id,
            *_live_level(),
        )
        .values(superseded_at=func.now())
        .returning(ctl.id),
    )
    columns = {
        "student_id": _typed(ctl.student_id, student_id),
        "competency_id": _typed(ctl.competency_id, competency_id),
        "academic_year_id": Class.academic_year_id,
        "term_id": _typed(ctl.term_id, term_id),
        "class_id": _typed(ctl.class_id, class_id),
        "scale_level_id": _typed(ctl.scale_level_id, level_id),
        "asserted_by_id": _typed(ctl.asserted_by_id, teacher_id),
        "note": _typed(ctl.note, note),
        "supersedes_id": _typed(ctl.supersedes_id, old["id"] if old else None),
    }
    return await scalar(
        conn,
        insert(ctl)
        .from_select(list(columns), select(*columns.values()).where(Class.id == class_id))
        .returning(ctl.id),
    )


def check_conclusion_length(body: str) -> None:
    """Reject a normalized conclusion SIAGIE would not accept, telling the teacher how far off."""
    n = domain.conclusion_length(body)
    if n < domain.CONCLUSION_MIN_CHARS:
        raise AppError(
            422,
            "conclusion_too_short",
            f"La conclusión tiene {n} caracteres; SIAGIE pide al menos"
            f" {domain.CONCLUSION_MIN_CHARS}.",
        )
    if n > domain.CONCLUSION_MAX_CHARS:
        raise AppError(
            422,
            "conclusion_too_long",
            f"La conclusión tiene {n} caracteres; SIAGIE acepta como máximo"
            f" {domain.CONCLUSION_MAX_CHARS}. Acórtala en {n - domain.CONCLUSION_MAX_CHARS}.",
        )


async def conclusion_requirement(
    conn: AsyncConnection,
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID,
    term_id: UUID,
) -> str:
    stage, cycle = await stage_and_cycle(conn, class_id)
    inclusion = await scalar(
        conn, select(Student.inclusion_support).where(Student.id == student_id)
    )
    ctl, gsl = CompetencyTermLevel, GradeScaleLevel
    level = await fetch_one(
        conn,
        select(gsl.code)
        .select_from(ctl)
        .join(gsl, gsl.id == ctl.scale_level_id)
        .where(
            ctl.student_id == student_id,
            ctl.competency_id == competency_id,
            ctl.term_id == term_id,
            *_live_level(),
        ),
    )
    level_code = level["code"] if level else None
    consecutive_c = False
    if level_code == domain.LEVEL_C:
        pt, t = aliased(Term, name="pt"), aliased(Term, name="t")
        consecutive_c = await scalar(
            conn,
            select(
                select(1)
                .select_from(ctl)
                .join(pt, pt.id == ctl.term_id)
                .join(t, t.id == term_id)
                .join(gsl, gsl.id == ctl.scale_level_id)
                .where(
                    ctl.student_id == student_id,
                    ctl.competency_id == competency_id,
                    pt.academic_year_id == t.academic_year_id,
                    pt.sequence == t.sequence - 1,
                    gsl.code == domain.LEVEL_C,
                    *_live_level(),
                )
                .exists()
            ),
        )
    return classify_conclusion_requirement(inclusion, stage, cycle, level_code, consecutive_c)


async def upsert_conclusion(
    conn: AsyncConnection,
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID,
    term_id: UUID,
    teacher_id: UUID,
    body: str,
    status: str,
    generation_id: UUID | None,
) -> UUID:
    """Write a conclusión descriptiva, superseding any previous one for the same competency and
    period. `requirement` is derived here, never taken from the request. The body is stored as
    SIAGIE receives it and must fit its 10 to 350 characters, draft or final.

    generation_id, when set, is the Mawta proposal the teacher started from: it must be a
    completed conclusions generation for this same student, competency and term. The text is
    still the teacher's. When that proposal read at least one voice note,
    generated_from_voice_notes is set; the flag is read from the generation, not the request.
    """
    body = domain.normalize_conclusion(body)
    check_conclusion_length(body)

    from_voice_notes = False
    if generation_id is not None:
        g = AgentGeneration
        used = g.result["used_voice_note_ids"]
        gen = await fetch_one(
            conn,
            select(
                func.coalesce(
                    (func.jsonb_typeof(used) == "array") & (func.jsonb_array_length(used) > 0),
                    false(),
                ).label("used_voice_notes")
            ).where(
                g.id == generation_id,
                g.agent == "conclusions",
                g.status == "completed",
                g.student_id == student_id,
                g.competency_id == competency_id,
                g.term_id == term_id,
            ),
        )
        if gen is None:
            raise AppError(
                422,
                "generation_mismatch",
                "La propuesta de Mawta no corresponde a esta competencia y periodo.",
            )
        from_voice_notes = gen["used_voice_notes"]

    requirement = await conclusion_requirement(conn, class_id, student_id, competency_id, term_id)

    dc = DescriptiveConclusion
    old = await fetch_one(
        conn,
        update(dc)
        .where(
            dc.student_id == student_id,
            dc.competency_id == competency_id,
            dc.term_id == term_id,
            dc.superseded_at.is_(None),
            dc.deleted_at.is_(None),
        )
        .values(superseded_at=func.now())
        .returning(dc.id),
    )
    columns = {
        "student_id": _typed(dc.student_id, student_id),
        "competency_id": _typed(dc.competency_id, competency_id),
        "academic_year_id": Class.academic_year_id,
        "term_id": _typed(dc.term_id, term_id),
        "class_id": _typed(dc.class_id, class_id),
        "body": _typed(dc.body, body),
        "requirement": _typed(dc.requirement, requirement),
        "status": _typed(dc.status, status),
        "authored_by_id": _typed(dc.authored_by_id, teacher_id),
        "supersedes_id": _typed(dc.supersedes_id, old["id"] if old else None),
        "generation_id": _typed(dc.generation_id, generation_id),
        "generated_from_voice_notes": literal(from_voice_notes, Boolean),
    }
    return await scalar(
        conn,
        insert(dc)
        .from_select(list(columns), select(*columns.values()).where(Class.id == class_id))
        .returning(dc.id),
    )
