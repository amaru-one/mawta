"""Term planning: editing planned evidences and the session outline."""

from datetime import date
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from db import fetch_one, fetch_required
from errors import AppError, NotFound
from repo.planning import (
    ExperienceHeader,
    _check_evidence_criteria,
    _place_evidence,
    _session_entry_at,
    _set_evidence_criteria,
    _unplace_entry,
    bad_input,
    check_evidence_kind,
    dedupe,
    list_experience_evidences,
    list_experience_sessions,
    lock_experience,
    resolve_evidence_scale,
    trimmed_or_none,
    unprocessable,
)
from repo.planning_plan import count_class_dates
from repo.planning_sync import sync_experience


async def _lock_planned_evidence(
    conn: AsyncConnection[DictRow], evidence_id: UUID
) -> ExperienceHeader:
    row = await fetch_one(
        conn,
        "select experience_id from planned_evidences where id = %s and deleted_at is null",
        (evidence_id,),
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró la evidencia")
    return await lock_experience(conn, row["experience_id"])


async def update_planned_evidence(
    conn: AsyncConnection[DictRow], evidence_id: UUID, patch: dict[str, Any]
) -> None:
    """Edit a planned evidence; editing a proposal accepts it. `patch` keys (present only when
    set): name, kind, value_scale, max_score, criterion_ids, session_date (None unplaces the
    evidence). Setting the scale to ordinal clears the maximum; setting only max_score keeps a
    numeric scale."""
    h = await _lock_planned_evidence(conn, evidence_id)
    name = None
    if "name" in patch:
        name = patch["name"].strip()
        if not name:
            raise bad_input("missing_name", "la evidencia necesita un nombre")
    if "kind" in patch:
        check_evidence_kind(patch["kind"])

    new_scale = None
    new_max = None
    if "value_scale" in patch or "max_score" in patch:
        cur = await fetch_required(
            conn,
            "select value_scale, max_score from planned_evidences where id = %s",
            (evidence_id,),
        )
        scale = cur["value_scale"]
        max_score = float(cur["max_score"]) if cur["max_score"] is not None else None
        if "value_scale" in patch:
            scale = patch["value_scale"]
            if scale != cur["value_scale"]:
                max_score = None  # the old maximum belongs to the old scale
        if "max_score" in patch:
            max_score = patch["max_score"]
        new_scale, new_max = resolve_evidence_scale(scale, max_score)

    if "criterion_ids" in patch:
        ids = dedupe(patch["criterion_ids"])
        await _check_evidence_criteria(conn, h.id, ids)
        await _set_evidence_criteria(conn, evidence_id, ids)
    if "session_date" in patch:
        entry_id = None
        if patch["session_date"] is not None:
            entry_id = await _session_entry_at(conn, h.id, patch["session_date"])
        await _place_evidence(conn, evidence_id, entry_id)

    await conn.execute(
        """
        update planned_evidences
           set name = coalesce(%(name)s::text, name), kind = coalesce(%(kind)s::text, kind),
               value_scale = coalesce(%(scale)s::text, value_scale),
               max_score = case when %(scale)s::text is null then max_score
                                else %(max)s::numeric end,
               accepted_at = coalesce(accepted_at, now())
         where id = %(id)s
        """,
        {
            "id": evidence_id,
            "name": name,
            "kind": patch.get("kind"),
            "scale": new_scale,
            "max": new_max,
        },
    )
    await sync_experience(conn, h.id)


async def accept_planned_evidence(conn: AsyncConnection[DictRow], evidence_id: UUID) -> None:
    h = await _lock_planned_evidence(conn, evidence_id)
    await conn.execute(
        "update planned_evidences set accepted_at = coalesce(accepted_at, now()) where id = %s",
        (evidence_id,),
    )
    await sync_experience(conn, h.id)


async def delete_planned_evidence(conn: AsyncConnection[DictRow], evidence_id: UUID) -> None:
    """Soft-delete a planned evidence, its criterion links and its place in the session outline."""
    h = await _lock_planned_evidence(conn, evidence_id)
    for sql in (
        "update planned_evidence_criteria set deleted_at = now()"
        " where evidence_id = %s and deleted_at is null",
        "update session_outline_entries set planned_evidence_id = null"
        " where planned_evidence_id = %s",
        "update planned_evidences set deleted_at = now(), session_entry_id = null where id = %s",
    ):
        await conn.execute(sql, (evidence_id,))
    await sync_experience(conn, h.id)


async def get_planned_evidence(conn: AsyncConnection[DictRow], evidence_id: UUID) -> dict[str, Any]:
    row = await fetch_required(
        conn,
        "select experience_id from planned_evidences where id = %s and deleted_at is null",
        (evidence_id,),
    )
    found = await list_experience_evidences(conn, row["experience_id"], evidence_id)
    if not found:
        raise NotFound
    return found[0]


# ------------------------------------------------------- session outline --


async def _check_session_date(
    conn: AsyncConnection[DictRow], h: ExperienceHeader, on: date
) -> None:
    """A class date of the experience: inside its range, with a non-cancelled session of the class,
    and not a non-teaching day."""
    if on < h.starts_on or on > h.ends_on:
        raise unprocessable("date_not_in_experience", "esa fecha está fuera de la experiencia")
    if await count_class_dates(conn, h.class_id, on, on) == 0:
        raise unprocessable(
            "date_not_in_experience", "esa fecha no es un día de clase de esta clase"
        )


async def put_session_entry(
    conn: AsyncConnection[DictRow], experience_id: UUID, on: date, inp: dict[str, Any]
) -> None:
    """Create or replace the session entry of a date, and accept it. The body is the entry's whole
    state: no planned_evidence_id empties the session. `inp` keys: title, topics,
    planned_evidence_id."""
    h = await lock_experience(conn, experience_id)
    title = inp["title"].strip()
    if not title:
        raise bad_input("missing_title", "la sesión necesita un título")
    await _check_session_date(conn, h, on)
    evidence_id = inp.get("planned_evidence_id")
    if evidence_id is not None:
        row = await fetch_required(
            conn,
            """
            select exists (
              select 1 from planned_evidences
               where id = %s and experience_id = %s and deleted_at is null
            ) as ok
            """,
            (evidence_id, h.id),
        )
        if not row["ok"]:
            raise unprocessable(
                "evidence_not_in_experience", "esa evidencia no es de esta experiencia"
            )

    topics = trimmed_or_none(inp.get("topics"))
    entry = await fetch_one(
        conn,
        """
        update session_outline_entries
           set title = %s, topics = %s, accepted_at = now()
         where experience_id = %s and class_date = %s and deleted_at is null
        returning id
        """,
        (title, topics, h.id, on),
    )
    if entry is None:
        entry = await fetch_required(
            conn,
            """
            insert into session_outline_entries
              (tenant_id, experience_id, class_date, title, topics, proposed_by, accepted_at)
            values (app.current_tenant_id(), %s, %s, %s, %s, 'teacher', now())
            returning id
            """,
            (h.id, on, title, topics),
        )
    if evidence_id is not None:
        await _place_evidence(conn, evidence_id, entry["id"])
    else:
        await _unplace_entry(conn, entry["id"])
    await sync_experience(conn, h.id)


async def propose_session_entry(
    conn: AsyncConnection[DictRow], experience_id: UUID, on: date, inp: dict[str, Any]
) -> bool:
    """Write a session entry the planning agent proposes, on a class date of the experience that
    has none yet. Never touches an existing entry: returns False when the date already had one. A
    proposed evidence must be of the experience and not yet placed anywhere."""
    h = await lock_experience(conn, experience_id)
    title = inp["title"].strip()
    if not title:
        raise bad_input("missing_title", "la sesión necesita un título")
    await _check_session_date(conn, h, on)
    evidence_id = inp.get("planned_evidence_id")
    if evidence_id is not None:
        row = await fetch_required(
            conn,
            """
            select exists (
              select 1 from planned_evidences
               where id = %s and experience_id = %s and deleted_at is null
                 and session_entry_id is null
            ) as ok
            """,
            (evidence_id, h.id),
        )
        if not row["ok"]:
            raise unprocessable(
                "evidence_not_in_experience",
                "esa evidencia no es de esta experiencia o ya está ubicada en otra sesión",
            )
    entry = await fetch_one(
        conn,
        """
        insert into session_outline_entries
          (tenant_id, experience_id, class_date, title, topics, proposed_by, accepted_at)
        values (app.current_tenant_id(), %s, %s, %s, %s, 'mawta', null)
        on conflict (tenant_id, experience_id, class_date) where deleted_at is null do nothing
        returning id
        """,
        (h.id, on, title, trimmed_or_none(inp.get("topics"))),
    )
    if entry is None:
        return False
    if evidence_id is not None:
        await _place_evidence(conn, evidence_id, entry["id"])
    return True


def _session_entry_not_found() -> AppError:
    return AppError(404, "not_found", "no hay una sesión planificada en esa fecha")


async def accept_session_entry(
    conn: AsyncConnection[DictRow], experience_id: UUID, on: date
) -> None:
    await lock_experience(conn, experience_id)
    cur = await conn.execute(
        """
        update session_outline_entries set accepted_at = coalesce(accepted_at, now())
         where experience_id = %s and class_date = %s and deleted_at is null
        """,
        (experience_id, on),
    )
    if cur.rowcount == 0:
        raise _session_entry_not_found()
    await sync_experience(conn, experience_id)


async def delete_session_entry(
    conn: AsyncConnection[DictRow], experience_id: UUID, on: date
) -> None:
    """Soft-delete the session entry of a date; the evidence it held stays in the experience,
    unplaced."""
    await lock_experience(conn, experience_id)
    entry = await fetch_one(
        conn,
        """
        select id from session_outline_entries
         where experience_id = %s and class_date = %s and deleted_at is null
        """,
        (experience_id, on),
    )
    if entry is None:
        raise _session_entry_not_found()
    await _unplace_entry(conn, entry["id"])
    await conn.execute(
        "update session_outline_entries set deleted_at = now() where id = %s", (entry["id"],)
    )
    # The class session keeps no name the plan gave it.
    await conn.execute(
        """
        update class_sessions cs set topic = null
          from learning_experiences le
         where le.id = %s and le.status = 'planificada'
           and cs.class_id = le.class_id and cs.session_date = %s and cs.deleted_at is null
        """,
        (experience_id, on),
    )
    await sync_experience(conn, experience_id)


async def get_session_entry(
    conn: AsyncConnection[DictRow], experience_id: UUID, on: date
) -> dict[str, Any]:
    found = await list_experience_sessions(conn, experience_id, on)
    if not found:
        raise _session_entry_not_found()
    return found[0]
