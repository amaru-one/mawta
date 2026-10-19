"""Capacidades and criterios de evaluación.

A criterio is the ruler, never the thing marked: it carries no level and must not grow one.
The one judgement this app records is the nivel de logro of a competencia, asserted by the
teacher after reading the period's evidence (RVM 094-2020, 5.1.1.3 p.2-3).
"""

from uuid import UUID

from psycopg import AsyncConnection

from mawta_api.db import fetch_all, fetch_required
from mawta_api.errors import AppError


async def list_competency_capabilities(
    conn: AsyncConnection, competency_id: UUID
) -> list[dict] | None:
    """The capacidades of one competencia, for the picker used when writing a criterio."""
    rows = await fetch_all(
        conn,
        """
        select id as capability_id, code, name from capabilities
         where competency_id = %s and is_active and deleted_at is null
         order by sort_order, code
        """,
        (competency_id,),
    )
    return rows or None


async def create_capability(
    conn: AsyncConnection, competency_id: UUID, code: str, name: str
) -> UUID:
    name = name.strip()
    if not name:
        raise AppError(400, "missing_name", "a capacidad needs a name")
    next_order = (
        await fetch_required(
            conn,
            """
            select coalesce(max(sort_order), 0) + 1 as n from capabilities
             where competency_id = %s and deleted_at is null
            """,
            (competency_id,),
        )
    )["n"]
    row = await fetch_required(
        conn,
        """
        insert into capabilities (tenant_id, competency_id, code, name, sort_order)
        values (app.current_tenant_id(), %s, %s, %s, %s)
        returning id
        """,
        (competency_id, code, name, next_order),
    )
    return row["id"]


async def list_class_criteria(conn: AsyncConnection, class_id: UUID) -> list[dict] | None:
    """Every competencia of the class's área with its general criterios (the ones written for
    the competencia rather than for an experiencia). Criterios of an experiencia are left out:
    they belong to one class's situation (RVM 094-2020, 5.1.1.1)."""
    rows = await fetch_all(
        conn,
        """
        with cls as (
          select co.subject_id
            from classes cl
            join courses co on co.id = cl.course_id
           where cl.id = %s and cl.deleted_at is null
        )
        select c.id as competency_id, c.code, c.name, c.kind,
               ec.id as criterion_id, ec.capability_id, ec.code as crit_code,
               ec.description, ec.sort_order,
               null::uuid as experience_id, null::text as experience_title
          from competencies c
          left join evaluation_criteria ec
                 on ec.competency_id = c.id and ec.experience_id is null
                and ec.is_active and ec.deleted_at is null
         where c.subject_id = (select subject_id from cls)
           and c.is_active and c.deleted_at is null
         order by c.sort_order, c.code, ec.sort_order nulls last, ec.code nulls last
        """,
        (class_id,),
    )
    return _fold_competency_criteria(rows)


async def list_evidence_criteria(
    conn: AsyncConnection, class_id: UUID, term_id: UUID
) -> list[dict] | None:
    """Every competencia of the class's área with the criterios a new piece of evidencia may be
    read against: the accepted criterios of the class's planned experiencias in the term. Drafts
    and pending proposals are not offered. A competencia with none comes back with an empty
    list, which the screen turns into "plan an experiencia first"."""
    rows = await fetch_all(
        conn,
        """
        with cls as (
          select co.subject_id
            from classes cl
            join courses co on co.id = cl.course_id
           where cl.id = %(class)s and cl.deleted_at is null
        ), crit as (
          select ec.*, le.id as exp_id, le.title as exp_title, le.starts_on as exp_starts_on
            from evaluation_criteria ec
            join learning_experiences le on le.id = ec.experience_id
           where le.class_id = %(class)s and le.term_id = %(term)s and le.status = 'planificada'
             and le.deleted_at is null
             and ec.accepted_at is not null and ec.is_active and ec.deleted_at is null
        )
        select c.id as competency_id, c.code, c.name, c.kind,
               crit.id as criterion_id, crit.capability_id, crit.code as crit_code,
               crit.description, crit.sort_order,
               crit.exp_id as experience_id, crit.exp_title as experience_title
          from competencies c
          left join crit on crit.competency_id = c.id
         where c.subject_id = (select subject_id from cls)
           and c.is_active and c.deleted_at is null
         order by c.sort_order, c.code, crit.exp_starts_on nulls last, crit.exp_id,
                  crit.sort_order nulls last, crit.created_at
        """,
        {"class": class_id, "term": term_id},
    )
    return _fold_competency_criteria(rows)


def _fold_competency_criteria(rows: list[dict]) -> list[dict] | None:
    """One row per (competencia, criterio) folded into one entry per competencia, in order."""
    out: list[dict] = []
    by_competency: dict[UUID, dict] = {}
    for r in rows:
        comp = by_competency.get(r["competency_id"])
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
    cur = await conn.execute(
        "update evaluation_criteria set deleted_at = now() where id = %s and deleted_at is null",
        (criterion_id,),
    )
    if cur.rowcount == 0:
        raise AppError(404, "not_found", "criterio not found")
    await conn.execute(
        """
        update planned_evidence_criteria set deleted_at = now()
         where criterion_id = %s and deleted_at is null
        """,
        (criterion_id,),
    )
