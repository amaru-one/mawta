"""Bring planned experiences up to date with the class calendar and evidence."""

import logging
from uuid import UUID

import psycopg
from psycopg import AsyncConnection

from mawta_api import applog
from mawta_api.db import fetch_all, fetch_one

logger = logging.getLogger("mawta-server")


async def sync_class_plan(conn: AsyncConnection, class_id: UUID) -> None:
    """sync_experience for every planned experience of a class. Idempotent, so screens that
    show the class calendar or the plan call it to bring experiences planned before the
    bridge existed up to date."""
    rows = await fetch_all(
        conn,
        """
        select id from learning_experiences
         where class_id = %s and status = 'planificada' and deleted_at is null
        """,
        (class_id,),
    )
    for row in rows:
        await sync_experience(conn, row["id"])


async def sync_experience(conn: AsyncConnection, experience_id: UUID) -> None:
    """Make a planned experience real:

    - each accepted session outline entry names the class session(s) of its date
      (class_sessions.topic), which is what the class calendar shows;
    - each accepted planned evidence becomes an assessment tagged with its criteria, so it
      reaches every student on the roster. It is valued the way the planned evidence says and
      linked to the class session of its date, which is also its due date.

    A draft experience is left alone. Only writes what differs, so calling it again is cheap.
    """
    exp = await fetch_one(
        conn,
        """
        select class_id, term_id, status from learning_experiences
         where id = %s and deleted_at is null
        """,
        (experience_id,),
    )
    if exp is None or exp["status"] != "planificada":
        return
    class_id, term_id = exp["class_id"], exp["term_id"]

    await conn.execute(
        """
        update class_sessions cs set topic = e.title
          from session_outline_entries e
         where e.experience_id = %(exp)s and e.deleted_at is null and e.accepted_at is not null
           and cs.class_id = %(class)s and cs.session_date = e.class_date
           and cs.deleted_at is null and cs.status <> 'cancelled'
           and cs.topic is distinct from e.title
        """,
        {"exp": experience_id, "class": class_id},
    )

    # Evidence that left the plan leaves the students' screens too. Scores already recorded
    # stay in the history, as with any deleted assessment.
    await conn.execute(
        """
        update assessments set deleted_at = now()
         where deleted_at is null
           and planned_evidence_id in (
             select id from planned_evidences
              where experience_id = %s and (deleted_at is not null or accepted_at is null))
        """,
        (experience_id,),
    )

    evidences = await fetch_all(
        conn,
        """
        select pe.id, pe.name, pe.kind, pe.value_scale, pe.max_score,
               e.class_date as date, a.id as assessment_id
          from planned_evidences pe
          left join session_outline_entries e
                 on e.id = pe.session_entry_id and e.deleted_at is null
          left join assessments a on a.planned_evidence_id = pe.id and a.deleted_at is null
         where pe.experience_id = %s and pe.deleted_at is null and pe.accepted_at is not null
         order by pe.created_at, pe.id
        """,
        (experience_id,),
    )

    for p in evidences:
        session_id = None
        due_at = None
        if p["date"] is not None:
            sess = await fetch_one(
                conn,
                """
                select id, scheduled_end_at from class_sessions
                 where class_id = %s and session_date = %s and deleted_at is null
                   and status <> 'cancelled'
                 order by scheduled_start_at limit 1
                """,
                (class_id, p["date"]),
            )
            if sess is not None:
                session_id, due_at = sess["id"], sess["scheduled_end_at"]
        # Both tables share the evidencia kinds, so the kind carries over as is.
        kind = p["kind"]
        max_score = float(p["max_score"]) if p["max_score"] is not None else None

        if p["assessment_id"] is not None:
            assessment_id = p["assessment_id"]
            await conn.execute(
                """
                update assessments set title = %(name)s, kind = %(kind)s,
                       session_id = %(session)s::uuid, due_at = %(due)s::timestamptz
                 where id = %(id)s
                   and (title is distinct from %(name)s::text or kind is distinct from %(kind)s::text
                        or session_id is distinct from %(session)s::uuid
                        or due_at is distinct from %(due)s::timestamptz)
                """,
                {
                    "id": assessment_id,
                    "name": p["name"],
                    "kind": kind,
                    "session": session_id,
                    "due": due_at,
                },
            )
            # The scale changes only while nobody has been valued yet: a mark already
            # recorded was written against the old one.
            await conn.execute(
                """
                update assessments a set value_scale = %(scale)s, max_score = %(max)s::numeric
                 where a.id = %(id)s
                   and (a.value_scale is distinct from %(scale)s::text
                        or a.max_score is distinct from %(max)s::numeric)
                   and not exists (select 1 from scores s
                                    where s.assessment_id = a.id and s.deleted_at is null)
                """,
                {"id": assessment_id, "scale": p["value_scale"], "max": max_score},
            )
        else:
            cur = await conn.execute(
                """
                insert into assessments (tenant_id, class_id, term_id, session_id,
                                         title, kind, value_scale, max_score, due_at,
                                         status, published_at, planned_evidence_id)
                values (app.current_tenant_id(), %s, %s, %s::uuid, %s, %s, %s, %s::numeric,
                        %s::timestamptz, 'published', now(), %s)
                returning id
                """,
                (
                    class_id,
                    term_id,
                    session_id,
                    p["name"],
                    kind,
                    p["value_scale"],
                    max_score,
                    due_at,
                    p["id"],
                ),
            )
            assessment_id = (await cur.fetchone())["id"]

        # assessment_criteria rows are soft-deleted, so a criterion that returns reuses its
        # old row.
        await conn.execute(
            """
            update assessment_criteria set deleted_at = now()
             where assessment_id = %s and deleted_at is null
               and criterion_id not in (
                 select criterion_id from planned_evidence_criteria
                  where evidence_id = %s and deleted_at is null)
            """,
            (assessment_id, p["id"]),
        )
        await conn.execute(
            """
            insert into assessment_criteria (tenant_id, assessment_id, criterion_id)
            select app.current_tenant_id(), %s, pc.criterion_id
              from planned_evidence_criteria pc
             where pc.evidence_id = %s and pc.deleted_at is null
            on conflict (tenant_id, assessment_id, criterion_id) do update set deleted_at = null
             where assessment_criteria.deleted_at is not null
            """,
            (assessment_id, p["id"]),
        )


async def heal_class_plan(conn: AsyncConnection, class_id: UUID) -> None:
    """sync_class_plan for read paths: runs in a savepoint and never fails the read. A class
    whose sync fails still shows its calendar; the evidence waits for the next sync."""
    try:
        async with conn.transaction():  # a nested block is a savepoint
            await sync_class_plan(conn, class_id)
    except psycopg.Error as exc:
        applog.warn(logger, "plan sync skipped", class_id=class_id, error=str(exc))
