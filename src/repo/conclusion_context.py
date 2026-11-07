"""What the descriptive-conclusions agent reads about one student, one competency and one term.
Every query is scoped by the ids the server put on the generation, never by anything the model asked
for."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Float, cast, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by, array
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.orm import aliased

from db import fetch_all, fetch_one, fetch_required, scalar
from mawta_schema.tables import (
    Assessment,
    AssessmentCriterion,
    Capability,
    Class,
    ClassSession,
    Competency,
    CompetencyTermLevel,
    Course,
    DescriptiveConclusion,
    EvaluationCriterion,
    EvaluationCriterionCapability,
    GradeScaleLevel,
    PlannedEvidence,
    Score,
    Term,
    VoiceNote,
)
from repo.competencies import conclusion_requirement as requirement_of
from repo.competencies import expected_standards, stage_and_cycle
from repo.planning import MIN_CONCLUSION_EVIDENCES
from repo.redaction import (
    ATTRIBUTION_DISCARDED,
    ATTRIBUTION_PENDING,
    student_names,
)
from repo.roster import roster_as_of

__all__ = ["MIN_CONCLUSION_EVIDENCES"]


async def conclusion_requirement(
    conn: AsyncConnection,
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID,
    term_id: UUID,
) -> str:
    """Why a conclusion is (or is not) mandatory for this competency, student and period."""
    return await requirement_of(conn, class_id, student_id, competency_id, term_id)


async def expected_standard(
    conn: AsyncConnection, class_id: UUID, competency_id: UUID
) -> dict[str, Any] | None:
    """The standard of the level expected at the end of the class's cycle for this competency:
    the reference the CNEB asks a conclusion to describe progress against. None when the class has
    no cycle or the competency has no standard at that level."""
    _, cycle = await stage_and_cycle(conn, class_id)
    return (await expected_standards(conn, cycle, [competency_id])).get(competency_id)


async def competency_in_class(conn: AsyncConnection, class_id: UUID, competency_id: UUID) -> bool:
    """Whether a competency belongs to the área the class teaches."""
    return await scalar(
        conn,
        select(
            select(1)
            .select_from(Competency)
            .join(Course, Course.subject_id == Competency.subject_id)
            .join(Class, Class.course_id == Course.id)
            .where(
                Class.id == class_id,
                Competency.id == competency_id,
                Competency.deleted_at.is_(None),
            )
            .exists()
        ),
    )


async def live_competency_level(
    conn: AsyncConnection, student_id: UUID, competency_id: UUID, term_id: UUID
) -> str | None:
    """The level a teacher asserted for this student, competency and term; None when none yet."""
    row = await fetch_one(
        conn,
        select(GradeScaleLevel.code)
        .select_from(CompetencyTermLevel)
        .join(GradeScaleLevel, GradeScaleLevel.id == CompetencyTermLevel.scale_level_id)
        .where(
            CompetencyTermLevel.student_id == student_id,
            CompetencyTermLevel.competency_id == competency_id,
            CompetencyTermLevel.term_id == term_id,
            CompetencyTermLevel.superseded_at.is_(None),
            CompetencyTermLevel.deleted_at.is_(None),
        ),
    )
    return row["code"] if row else None


async def get_competency_brief(conn: AsyncConnection, competency_id: UUID) -> dict[str, Any]:
    """A competency with its active capabilities: {id, code, name, description, capabilities}."""
    comp = dict(
        await fetch_required(
            conn,
            select(Competency.id, Competency.code, Competency.name, Competency.description).where(
                Competency.id == competency_id, Competency.deleted_at.is_(None)
            ),
        )
    )
    capabilities = await fetch_all(
        conn,
        select(Capability.id, Capability.code, Capability.name)
        .where(
            Capability.competency_id == competency_id,
            Capability.is_active,
            Capability.deleted_at.is_(None),
        )
        .order_by(Capability.sort_order, Capability.code),
    )
    comp["capabilities"] = [dict(c) for c in capabilities]
    return comp


def graded(evidence: dict[str, Any]) -> bool:
    """Whether the evidence carries a value for this student."""
    return evidence["score_status"] == "graded"


async def list_conclusion_evidence(
    conn: AsyncConnection,
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID,
    term_id: UUID,
) -> list[dict[str, Any]]:
    """The published evidences of a class and term that apply to the student and are read against
    at least one criterion of the competency. Only that competency's criteria are attached, and the
    score's feedback is included: it is the teacher's own words about the work."""
    a, ec = Assessment, EvaluationCriterion
    rows = await fetch_all(
        conn,
        select(
            a.id,
            a.title,
            a.description,
            a.kind,
            a.value_scale,
            a.due_at,
            Score.status.label("score_status"),
            cast(Score.raw_value, Float).label("raw_value"),
            cast(Score.max_value, Float).label("max_value"),
            GradeScaleLevel.code.label("scale_level"),
            Score.feedback,
            PlannedEvidence.experience_id,
        )
        .outerjoin(
            Score,
            (Score.assessment_id == a.id)
            & (Score.student_id == student_id)
            & Score.superseded_at.is_(None)
            & Score.deleted_at.is_(None),
        )
        .outerjoin(GradeScaleLevel, GradeScaleLevel.id == Score.scale_level_id)
        .outerjoin(
            PlannedEvidence,
            (PlannedEvidence.id == a.planned_evidence_id) & PlannedEvidence.deleted_at.is_(None),
        )
        .where(
            a.class_id == class_id,
            a.term_id == term_id,
            a.status.in_(("published", "closed")),
            a.deleted_at.is_(None),
            a.student_id.is_(None) | (a.student_id == student_id),
            select(1)
            .select_from(AssessmentCriterion)
            .join(ec, ec.id == AssessmentCriterion.criterion_id)
            .where(
                AssessmentCriterion.assessment_id == a.id,
                ec.competency_id == competency_id,
                ec.deleted_at.is_(None),
            )
            .exists(),
        )
        .order_by(func.coalesce(a.due_at, a.created_at), a.id),
    )
    out = [{**r, "criteria": []} for r in rows]
    if not out:
        return out
    index = {e["id"]: e for e in out}
    # Capabilities come from evaluation_criterion_capabilities (N:M); a criterion without rows
    # there falls back to its own capability_id.
    ecc = EvaluationCriterionCapability
    linked = (
        select(func.array_agg(aggregate_order_by(ecc.capability_id, ecc.capability_id)))
        .where(ecc.criterion_id == ec.id, ecc.deleted_at.is_(None))
        .scalar_subquery()
    )
    for c in await fetch_all(
        conn,
        select(
            AssessmentCriterion.assessment_id,
            ec.id,
            ec.description,
            func.coalesce(linked, array([ec.capability_id])).label("capability_ids"),
        )
        .join(ec, ec.id == AssessmentCriterion.criterion_id)
        .where(
            AssessmentCriterion.assessment_id.in_(list(index)),
            ec.competency_id == competency_id,
            ec.deleted_at.is_(None),
        )
        .order_by(AssessmentCriterion.assessment_id, ec.sort_order, ec.id),
    ):
        index[c["assessment_id"]]["criteria"].append(
            {
                "id": c["id"],
                "description": c["description"],
                "capability_ids": c["capability_ids"],
            }
        )
    return out


def _notes_of(class_id: UUID, student_id: UUID, term_id: UUID):
    return (
        VoiceNote.class_id == class_id,
        VoiceNote.student_id == student_id,
        ClassSession.term_id == term_id,
        VoiceNote.deleted_at.is_(None),
    )


async def list_conclusion_voice_notes(
    conn: AsyncConnection, class_id: UUID, student_id: UUID, term_id: UUID
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The student's swept, usable voice notes of the class in the term, oldest first, and counts
    of the discarded ones and the ones not swept yet (still transcribing or waiting for the
    sweep). Returns (notes, {"discarded": n, "pending": n})."""
    rows = await fetch_all(
        conn,
        select(
            VoiceNote.id,
            VoiceNote.recorded_at,
            ClassSession.topic.label("session_topic"),
            VoiceNote.transcript_redacted.label("redacted"),
            VoiceNote.attribution_status.label("status"),
            VoiceNote.transcription_status.label("transcription"),
        )
        .join(ClassSession, ClassSession.id == VoiceNote.session_id)
        .where(*_notes_of(class_id, student_id, term_id))
        .order_by(VoiceNote.recorded_at, VoiceNote.id),
    )
    counts = {"discarded": 0, "pending": 0}
    out: list[dict[str, Any]] = []
    for r in rows:
        if r["status"] == ATTRIBUTION_DISCARDED:
            counts["discarded"] += 1
        elif r["status"] == ATTRIBUTION_PENDING:
            # Failed or skipped transcriptions will never be swept: they are not "in process",
            # just absent.
            if r["transcription"] not in ("failed", "skipped"):
                counts["pending"] += 1
        elif r["redacted"]:
            out.append(
                {
                    "id": r["id"],
                    "recorded_at": r["recorded_at"],
                    "session_topic": r["session_topic"],
                    "transcript_redacted": r["redacted"],
                }
            )
    return out, counts


async def list_discarded_voice_notes(
    conn: AsyncConnection, class_id: UUID, student_id: UUID, term_id: UUID
) -> list[dict[str, Any]]:
    """The student's discarded notes in a class and term, newest first. Shown to the teacher only
    when discarding them leaves too little evidence; the teacher recorded them, so the original
    transcript is shown."""
    rows = await fetch_all(
        conn,
        select(
            VoiceNote.id,
            VoiceNote.recorded_at,
            VoiceNote.duration_ms,
            VoiceNote.transcript,
            VoiceNote.discard_reason,
        )
        .join(ClassSession, ClassSession.id == VoiceNote.session_id)
        .where(
            *_notes_of(class_id, student_id, term_id),
            VoiceNote.attribution_status == ATTRIBUTION_DISCARDED,
        )
        .order_by(VoiceNote.recorded_at.desc(), VoiceNote.id),
    )
    return [dict(r) for r in rows]


async def list_earlier_term_conclusions(
    conn: AsyncConnection, student_id: UUID, competency_id: UUID, term_id: UUID
) -> list[dict[str, Any]]:
    """Oldest first, the student's live level and conclusion for the competency in the terms before
    term_id in the same academic year. A justification for consecutive C needs them."""
    pt = aliased(Term, name="pt")
    ctl, dc = CompetencyTermLevel, DescriptiveConclusion
    rows = await fetch_all(
        conn,
        select(
            pt.name.label("term_name"),
            pt.sequence,
            GradeScaleLevel.code.label("level"),
            dc.body,
        )
        .select_from(Term)
        .join(
            pt,
            (pt.academic_year_id == Term.academic_year_id)
            & (func.coalesce(pt.stage, "") == func.coalesce(Term.stage, ""))
            & (pt.sequence < Term.sequence)
            & pt.deleted_at.is_(None),
        )
        .outerjoin(
            ctl,
            (ctl.term_id == pt.id)
            & (ctl.student_id == student_id)
            & (ctl.competency_id == competency_id)
            & ctl.superseded_at.is_(None)
            & ctl.deleted_at.is_(None),
        )
        .outerjoin(GradeScaleLevel, GradeScaleLevel.id == ctl.scale_level_id)
        .outerjoin(
            dc,
            (dc.term_id == pt.id)
            & (dc.student_id == student_id)
            & (dc.competency_id == competency_id)
            & dc.superseded_at.is_(None)
            & dc.deleted_at.is_(None),
        )
        .where(Term.id == term_id)
        .order_by(pt.sequence),
    )
    return [dict(r) for r in rows if r["level"] is not None or r["body"] is not None]


async def roster_names(
    conn: AsyncConnection, class_id: UUID, student_id: UUID, today: date
) -> list[dict[str, Any]]:
    """Every name of the students on a class's roster today and of the given student, for the
    final check that a proposed conclusion names no one."""
    ids = await roster_as_of(conn, class_id, today)
    return await student_names(conn, [*ids, student_id])
