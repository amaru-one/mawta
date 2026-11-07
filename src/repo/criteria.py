"""Capacidades and criterios de evaluación.

A criterio is the ruler, never the thing marked: it carries no level and must not grow one.
The one judgement this app records is the nivel de logro of a competencia, asserted by the
teacher after reading the period's evidence (RVM 094-2020, 5.1.1.3 p.2-3).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping, Text, func, insert, null, select, type_coerce, update
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_all, fetch_required, scalar
from errors import AppError
from mawta_schema.tables import (
    Capability,
    Class,
    Competency,
    Course,
    EvaluationCriterion,
    LearningExperience,
    PlannedEvidenceCriterion,
)


async def list_competency_capabilities(
    conn: AsyncConnection, competency_id: UUID
) -> list[dict[str, Any]] | None:
    """The capacidades of one competencia, for the picker used when writing a criterio."""
    rows = await fetch_all(
        conn,
        select(Capability.id.label("capability_id"), Capability.code, Capability.name)
        .where(
            Capability.competency_id == competency_id,
            Capability.is_active,
            Capability.deleted_at.is_(None),
        )
        .order_by(Capability.sort_order, Capability.code),
    )
    return [dict(r) for r in rows] or None


async def create_capability(
    conn: AsyncConnection, competency_id: UUID, code: str, name: str
) -> UUID:
    name = name.strip()
    if not name:
        raise AppError(400, "missing_name", "a capacidad needs a name")
    next_order = await scalar(
        conn,
        select(func.coalesce(func.max(Capability.sort_order), 0) + 1).where(
            Capability.competency_id == competency_id, Capability.deleted_at.is_(None)
        ),
    )
    row = await fetch_required(
        conn,
        insert(Capability)
        .values(competency_id=competency_id, code=code, name=name, sort_order=next_order)
        .returning(Capability.id),
    )
    return row["id"]


def _class_subject(class_id: UUID):
    """The subject a class teaches, as a scalar subquery."""
    return (
        select(Course.subject_id)
        .select_from(Class)
        .join(Course, Course.id == Class.course_id)
        .where(Class.id == class_id, Class.deleted_at.is_(None))
        .scalar_subquery()
    )


_COMPETENCY = (
    Competency.id.label("competency_id"),
    Competency.code,
    Competency.name,
    Competency.kind,
)


async def list_class_criteria(conn: AsyncConnection, class_id: UUID) -> list[dict[str, Any]] | None:
    """Every competencia of the class's área with its general criterios (the ones written for
    the competencia rather than for an experiencia). Criterios of an experiencia are left out:
    they belong to one class's situation (RVM 094-2020, 5.1.1.1)."""
    ec = EvaluationCriterion
    rows = await fetch_all(
        conn,
        select(
            *_COMPETENCY,
            ec.id.label("criterion_id"),
            ec.capability_id,
            ec.code.label("crit_code"),
            ec.description,
            ec.sort_order,
            type_coerce(null(), PgUUID(as_uuid=True)).label("experience_id"),
            type_coerce(null(), Text).label("experience_title"),
        )
        .outerjoin(
            ec,
            (ec.competency_id == Competency.id)
            & ec.experience_id.is_(None)
            & ec.is_active
            & ec.deleted_at.is_(None),
        )
        .where(
            Competency.subject_id == _class_subject(class_id),
            Competency.is_active,
            Competency.deleted_at.is_(None),
        )
        .order_by(
            Competency.sort_order,
            Competency.code,
            ec.sort_order.asc().nulls_last(),
            ec.code.asc().nulls_last(),
        ),
    )
    return _fold_competency_criteria(rows)


async def list_evidence_criteria(
    conn: AsyncConnection, class_id: UUID, term_id: UUID
) -> list[dict[str, Any]] | None:
    """Every competencia of the class's área with the criterios a new piece of evidencia may be
    read against: the accepted criterios of the class's planned experiencias in the term. Drafts
    and pending proposals are not offered. A competencia with none comes back with an empty
    list, which the screen turns into "plan an experiencia first"."""
    ec, le = EvaluationCriterion, LearningExperience
    crit = (
        select(
            ec.id,
            ec.competency_id,
            ec.capability_id,
            ec.code,
            ec.description,
            ec.sort_order,
            ec.created_at,
            le.id.label("exp_id"),
            le.title.label("exp_title"),
            le.starts_on.label("exp_starts_on"),
        )
        .join(le, le.id == ec.experience_id)
        .where(
            le.class_id == class_id,
            le.term_id == term_id,
            le.status == "planificada",
            le.deleted_at.is_(None),
            ec.accepted_at.is_not(None),
            ec.is_active,
            ec.deleted_at.is_(None),
        )
        .cte("crit")
    )
    rows = await fetch_all(
        conn,
        select(
            *_COMPETENCY,
            crit.c.id.label("criterion_id"),
            crit.c.capability_id,
            crit.c.code.label("crit_code"),
            crit.c.description,
            crit.c.sort_order,
            crit.c.exp_id.label("experience_id"),
            crit.c.exp_title.label("experience_title"),
        )
        .outerjoin(crit, crit.c.competency_id == Competency.id)
        .where(
            Competency.subject_id == _class_subject(class_id),
            Competency.is_active,
            Competency.deleted_at.is_(None),
        )
        .order_by(
            Competency.sort_order,
            Competency.code,
            crit.c.exp_starts_on.asc().nulls_last(),
            crit.c.exp_id,
            crit.c.sort_order.asc().nulls_last(),
            crit.c.created_at,
        ),
    )
    return _fold_competency_criteria(rows)


def _fold_competency_criteria(rows: list[RowMapping]) -> list[dict[str, Any]] | None:
    """One row per (competencia, criterio) folded into one entry per competencia, in order."""
    out: list[dict[str, Any]] = []
    by_competency: dict[UUID, dict[str, Any]] = {}
    for r in rows:
        comp: dict[str, Any] | None = by_competency.get(r["competency_id"])
        if comp is None:
            comp = {
                "competency_id": r["competency_id"],
                "code": r["code"],
                "name": r["name"],
                "kind": r["kind"],
                "criteria": [],
            }
            by_competency[r["competency_id"]] = comp
            out.append(comp)
        if r["criterion_id"] is not None:
            crit = {
                "criterion_id": r["criterion_id"],
                "capability_id": r["capability_id"],
                "code": r["crit_code"],
                "description": r["description"],
                "sort_order": r["sort_order"],
            }
            if r["experience_id"] is not None:
                crit["experience_id"] = r["experience_id"]
            if r["experience_title"] is not None:
                crit["experience_title"] = r["experience_title"]
            comp["criteria"].append(crit)
    return out or None


async def delete_criterion(conn: AsyncConnection, criterion_id: UUID) -> None:
    """Soft-delete a criterio. Evidence already tagged with it keeps the tag; a planned evidence
    is a promise of what will be observed, not a record, so the deleted criterio leaves its list."""
    result = await conn.execute(
        update(EvaluationCriterion)
        .where(EvaluationCriterion.id == criterion_id, EvaluationCriterion.deleted_at.is_(None))
        .values(deleted_at=func.now())
    )
    if result.rowcount == 0:
        raise AppError(404, "not_found", "criterio not found")
    await conn.execute(
        update(PlannedEvidenceCriterion)
        .where(
            PlannedEvidenceCriterion.criterion_id == criterion_id,
            PlannedEvidenceCriterion.deleted_at.is_(None),
        )
        .values(deleted_at=func.now())
    )
