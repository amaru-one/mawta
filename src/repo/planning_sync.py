"""Bring planned experiences up to date with the class calendar and evidence."""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import Numeric, func, insert, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

import applog
from db import fetch_all, fetch_one, scalar
from mawta_schema.tables import (
    Assessment,
    AssessmentCriterion,
    ClassSession,
    LearningExperience,
    PlannedEvidence,
    PlannedEvidenceCriterion,
    Score,
    SessionOutlineEntry,
)

logger = logging.getLogger("mawta")


async def sync_class_plan(conn: AsyncConnection, class_id: UUID) -> None:
    """sync_experience for every planned experience of a class. Idempotent, so screens that
    show the class calendar or the plan call it to bring experiences planned before the
    bridge existed up to date."""
    le = LearningExperience
    result = await conn.execute(
        select(le.id).where(
            le.class_id == class_id, le.status == "planificada", le.deleted_at.is_(None)
        )
    )
    for experience_id in list(result.scalars()):
        await sync_experience(conn, experience_id)


async def sync_experience(conn: AsyncConnection, experience_id: UUID) -> None:
    """Make a planned experience real:

    - each accepted session outline entry names the class session(s) of its date
      (class_sessions.topic), which is what the class calendar shows;
    - each accepted planned evidence becomes an assessment tagged with its criteria, so it
      reaches every student on the roster. It is valued the way the planned evidence says and
      linked to the class session of its date, which is also its due date.

    A draft experience is left alone. Only writes what differs, so calling it again is cheap.
    """
    le, e, cs, pe, a = (
        LearningExperience,
        SessionOutlineEntry,
        ClassSession,
        PlannedEvidence,
        Assessment,
    )
    exp = await fetch_one(
        conn,
        select(le.class_id, le.term_id, le.status).where(
            le.id == experience_id, le.deleted_at.is_(None)
        ),
    )
    if exp is None or exp["status"] != "planificada":
        return
    class_id, term_id = exp["class_id"], exp["term_id"]

    await conn.execute(
        update(cs)
        .where(
            e.experience_id == experience_id,
            e.deleted_at.is_(None),
            e.accepted_at.is_not(None),
            cs.class_id == class_id,
            cs.session_date == e.class_date,
            cs.deleted_at.is_(None),
            cs.status != "cancelled",
            cs.topic.is_distinct_from(e.title),
        )
        .values(topic=e.title)
    )

    # Evidence that left the plan leaves the students' screens too. Scores already recorded
    # stay in the history, as with any deleted assessment.
    gone = select(pe.id).where(
        pe.experience_id == experience_id,
        or_(pe.deleted_at.is_not(None), pe.accepted_at.is_(None)),
    )
    await conn.execute(
        update(a)
        .where(a.deleted_at.is_(None), a.planned_evidence_id.in_(gone))
        .values(deleted_at=func.now())
    )

    evidences = await fetch_all(
        conn,
        select(
            pe.id,
            pe.name,
            pe.kind,
            pe.value_scale,
            pe.max_score,
            e.class_date.label("date"),
            a.id.label("assessment_id"),
        )
        .outerjoin(e, (e.id == pe.session_entry_id) & e.deleted_at.is_(None))
        .outerjoin(a, (a.planned_evidence_id == pe.id) & a.deleted_at.is_(None))
        .where(
            pe.experience_id == experience_id,
            pe.deleted_at.is_(None),
            pe.accepted_at.is_not(None),
        )
        .order_by(pe.created_at, pe.id),
    )

    for p in evidences:
        session_id = None
        due_at = None
        if p["date"] is not None:
            sess = await fetch_one(
                conn,
                select(cs.id, cs.scheduled_end_at)
                .where(
                    cs.class_id == class_id,
                    cs.session_date == p["date"],
                    cs.deleted_at.is_(None),
                    cs.status != "cancelled",
                )
                .order_by(cs.scheduled_start_at)
                .limit(1),
            )
            if sess is not None:
                session_id, due_at = sess["id"], sess["scheduled_end_at"]
        # Both tables share the evidencia kinds, so the kind carries over as is.
        kind = p["kind"]
        max_score = float(p["max_score"]) if p["max_score"] is not None else None

        if p["assessment_id"] is not None:
            assessment_id = p["assessment_id"]
            await conn.execute(
                update(a)
                .where(
                    a.id == assessment_id,
                    or_(
                        a.title.is_distinct_from(p["name"]),
                        a.kind.is_distinct_from(kind),
                        a.session_id.is_distinct_from(session_id),
                        a.due_at.is_distinct_from(due_at),
                    ),
                )
                .values(title=p["name"], kind=kind, session_id=session_id, due_at=due_at)
            )
            # The scale changes only while nobody has been valued yet: a mark already
            # recorded was written against the old one.
            max_value: Any = literal(max_score, Numeric)
            valued = (
                select(1).where(Score.assessment_id == a.id, Score.deleted_at.is_(None)).exists()
            )
            await conn.execute(
                update(a)
                .where(
                    a.id == assessment_id,
                    or_(
                        a.value_scale.is_distinct_from(p["value_scale"]),
                        a.max_score.is_distinct_from(max_value),
                    ),
                    ~valued,
                )
                .values(value_scale=p["value_scale"], max_score=max_value)
            )
        else:
            assessment_id = await scalar(
                conn,
                insert(a)
                .values(
                    class_id=class_id,
                    term_id=term_id,
                    session_id=session_id,
                    title=p["name"],
                    kind=kind,
                    value_scale=p["value_scale"],
                    max_score=max_score,
                    due_at=due_at,
                    status="published",
                    published_at=func.now(),
                    planned_evidence_id=p["id"],
                )
                .returning(a.id),
            )

        # assessment_criteria rows are soft-deleted, so a criterion that returns reuses its
        # old row.
        ac, pc = AssessmentCriterion, PlannedEvidenceCriterion
        planned_criteria = select(pc.criterion_id).where(
            pc.evidence_id == p["id"], pc.deleted_at.is_(None)
        )
        await conn.execute(
            update(ac)
            .where(
                ac.assessment_id == assessment_id,
                ac.deleted_at.is_(None),
                ~ac.criterion_id.in_(planned_criteria),
            )
            .values(deleted_at=func.now())
        )
        stmt = pg_insert(ac).from_select(
            ["assessment_id", "criterion_id"],
            select(literal(assessment_id, ac.assessment_id.type), pc.criterion_id).where(
                pc.evidence_id == p["id"], pc.deleted_at.is_(None)
            ),
        )
        await conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[ac.assessment_id, ac.criterion_id],
                set_={"deleted_at": None},
                where=ac.deleted_at.is_not(None),
            )
        )


async def heal_class_plan(conn: AsyncConnection, class_id: UUID) -> None:
    """sync_class_plan for read paths: runs in a savepoint and never fails the read. A class
    whose sync fails still shows its calendar; the evidence waits for the next sync."""
    try:
        async with conn.begin_nested():
            await sync_class_plan(conn, class_id)
    except DBAPIError as exc:
        applog.warn(logger, "plan sync skipped", class_id=class_id, error=str(exc))
