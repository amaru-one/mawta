"""Term planning: editing planned evidences and the session outline."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_one, fetch_required, scalar
from errors import AppError, NotFound
from mawta_schema.tables import (
    ClassSession,
    LearningExperience,
    PlannedEvidence,
    PlannedEvidenceCriterion,
    SessionOutlineEntry,
)
from repo.planning import (
    ExperienceHeader,
    bad_input,
    check_evidence_criteria,
    check_evidence_kind,
    dedupe,
    list_experience_evidences,
    list_experience_sessions,
    lock_experience,
    place_evidence,
    resolve_evidence_scale,
    session_entry_at,
    set_evidence_criteria,
    trimmed_or_none,
    unplace_entry,
    unprocessable,
)
from repo.planning_plan import count_class_dates
from repo.planning_sync import sync_experience


async def _lock_planned_evidence(conn: AsyncConnection, evidence_id: UUID) -> ExperienceHeader:
    pe = PlannedEvidence
    row = await fetch_one(
        conn,
        select(pe.experience_id).where(pe.id == evidence_id, pe.deleted_at.is_(None)),
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró la evidencia")
    return await lock_experience(conn, row["experience_id"])


async def update_planned_evidence(
    conn: AsyncConnection, evidence_id: UUID, patch: dict[str, Any]
) -> None:
    """Edit a planned evidence; editing a proposal accepts it. `patch` keys (present only when
    set): name, kind, value_scale, max_score, criterion_ids, session_date (None unplaces the
    evidence). Setting the scale to ordinal clears the maximum; setting only max_score keeps a
    numeric scale."""
    h = await _lock_planned_evidence(conn, evidence_id)
    pe = PlannedEvidence
    values: dict[str, Any] = {"accepted_at": func.coalesce(pe.accepted_at, func.now())}
    if "name" in patch:
        name = patch["name"].strip()
        if not name:
            raise bad_input("missing_name", "la evidencia necesita un nombre")
        values["name"] = name
    if "kind" in patch:
        check_evidence_kind(patch["kind"])
        if patch["kind"] is not None:
            values["kind"] = patch["kind"]

    if "value_scale" in patch or "max_score" in patch:
        cur = await fetch_required(
            conn, select(pe.value_scale, pe.max_score).where(pe.id == evidence_id)
        )
        scale = cur["value_scale"]
        max_score = float(cur["max_score"]) if cur["max_score"] is not None else None
        if "value_scale" in patch:
            scale = patch["value_scale"]
            if scale != cur["value_scale"]:
                max_score = None  # the old maximum belongs to the old scale
        if "max_score" in patch:
            max_score = patch["max_score"]
        values["value_scale"], values["max_score"] = resolve_evidence_scale(scale, max_score)

    if "criterion_ids" in patch:
        ids = dedupe(patch["criterion_ids"])
        await check_evidence_criteria(conn, h.id, ids)
        await set_evidence_criteria(conn, evidence_id, ids)
    if "session_date" in patch:
        entry_id = None
        if patch["session_date"] is not None:
            entry_id = await session_entry_at(conn, h.id, patch["session_date"])
        await place_evidence(conn, evidence_id, entry_id)

    await conn.execute(update(pe).where(pe.id == evidence_id).values(**values))
    await sync_experience(conn, h.id)


async def accept_planned_evidence(conn: AsyncConnection, evidence_id: UUID) -> None:
    h = await _lock_planned_evidence(conn, evidence_id)
    pe = PlannedEvidence
    await conn.execute(
        update(pe)
        .where(pe.id == evidence_id)
        .values(accepted_at=func.coalesce(pe.accepted_at, func.now()))
    )
    await sync_experience(conn, h.id)


async def delete_planned_evidence(conn: AsyncConnection, evidence_id: UUID) -> None:
    """Soft-delete a planned evidence, its criterion links and its place in the session outline."""
    h = await _lock_planned_evidence(conn, evidence_id)
    pc, se, pe = PlannedEvidenceCriterion, SessionOutlineEntry, PlannedEvidence
    for stmt in (
        update(pc)
        .where(pc.evidence_id == evidence_id, pc.deleted_at.is_(None))
        .values(deleted_at=func.now()),
        update(se).where(se.planned_evidence_id == evidence_id).values(planned_evidence_id=None),
        update(pe).where(pe.id == evidence_id).values(deleted_at=func.now(), session_entry_id=None),
    ):
        await conn.execute(stmt)
    await sync_experience(conn, h.id)


async def get_planned_evidence(conn: AsyncConnection, evidence_id: UUID) -> dict[str, Any]:
    pe = PlannedEvidence
    row = await fetch_required(
        conn, select(pe.experience_id).where(pe.id == evidence_id, pe.deleted_at.is_(None))
    )
    found = await list_experience_evidences(conn, row["experience_id"], evidence_id)
    if not found:
        raise NotFound
    return found[0]


# ------------------------------------------------------- session outline --


async def _check_session_date(conn: AsyncConnection, h: ExperienceHeader, on: date) -> None:
    """A class date of the experience: inside its range, with a non-cancelled session of the class,
    and not a non-teaching day."""
    if on < h.starts_on or on > h.ends_on:
        raise unprocessable("date_not_in_experience", "esa fecha está fuera de la experiencia")
    if await count_class_dates(conn, h.class_id, on, on) == 0:
        raise unprocessable(
            "date_not_in_experience", "esa fecha no es un día de clase de esta clase"
        )


async def _evidence_of(
    conn: AsyncConnection, evidence_id: UUID, experience_id: UUID, unplaced: bool = False
) -> bool:
    pe = PlannedEvidence
    where = [pe.id == evidence_id, pe.experience_id == experience_id, pe.deleted_at.is_(None)]
    if unplaced:
        where.append(pe.session_entry_id.is_(None))
    return await scalar(conn, select(select(1).where(*where).exists()))


async def put_session_entry(
    conn: AsyncConnection, experience_id: UUID, on: date, inp: dict[str, Any]
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
    if evidence_id is not None and not await _evidence_of(conn, evidence_id, h.id):
        raise unprocessable("evidence_not_in_experience", "esa evidencia no es de esta experiencia")

    topics = trimmed_or_none(inp.get("topics"))
    se = SessionOutlineEntry
    row = await fetch_one(
        conn,
        update(se)
        .where(se.experience_id == h.id, se.class_date == on, se.deleted_at.is_(None))
        .values(title=title, topics=topics, accepted_at=func.now())
        .returning(se.id),
    )
    if row is not None:
        entry_id = row["id"]
    else:
        entry_id = await scalar(
            conn,
            insert(se)
            .values(
                experience_id=h.id,
                class_date=on,
                title=title,
                topics=topics,
                proposed_by="teacher",
                accepted_at=func.now(),
            )
            .returning(se.id),
        )
    if evidence_id is not None:
        await place_evidence(conn, evidence_id, entry_id)
    else:
        await unplace_entry(conn, entry_id)
    await sync_experience(conn, h.id)


async def propose_session_entry(
    conn: AsyncConnection, experience_id: UUID, on: date, inp: dict[str, Any]
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
    if evidence_id is not None and not await _evidence_of(conn, evidence_id, h.id, unplaced=True):
        raise unprocessable(
            "evidence_not_in_experience",
            "esa evidencia no es de esta experiencia o ya está ubicada en otra sesión",
        )
    se = SessionOutlineEntry
    entry = await fetch_one(
        conn,
        pg_insert(se)
        .values(
            experience_id=h.id,
            class_date=on,
            title=title,
            topics=trimmed_or_none(inp.get("topics")),
            proposed_by="mawta",
            accepted_at=None,
        )
        .on_conflict_do_nothing(
            index_elements=[se.experience_id, se.class_date], index_where=se.deleted_at.is_(None)
        )
        .returning(se.id),
    )
    if entry is None:
        return False
    if evidence_id is not None:
        await place_evidence(conn, evidence_id, entry["id"])
    return True


def _session_entry_not_found() -> AppError:
    return AppError(404, "not_found", "no hay una sesión planificada en esa fecha")


async def accept_session_entry(conn: AsyncConnection, experience_id: UUID, on: date) -> None:
    await lock_experience(conn, experience_id)
    se = SessionOutlineEntry
    result = await conn.execute(
        update(se)
        .where(se.experience_id == experience_id, se.class_date == on, se.deleted_at.is_(None))
        .values(accepted_at=func.coalesce(se.accepted_at, func.now()))
    )
    if result.rowcount == 0:
        raise _session_entry_not_found()
    await sync_experience(conn, experience_id)


async def delete_session_entry(conn: AsyncConnection, experience_id: UUID, on: date) -> None:
    """Soft-delete the session entry of a date; the evidence it held stays in the experience,
    unplaced."""
    await lock_experience(conn, experience_id)
    se = SessionOutlineEntry
    entry = await fetch_one(
        conn,
        select(se.id).where(
            se.experience_id == experience_id, se.class_date == on, se.deleted_at.is_(None)
        ),
    )
    if entry is None:
        raise _session_entry_not_found()
    await unplace_entry(conn, entry["id"])
    await conn.execute(update(se).where(se.id == entry["id"]).values(deleted_at=func.now()))
    # The class session keeps no name the plan gave it.
    le, cs = LearningExperience, ClassSession
    await conn.execute(
        update(cs)
        .where(
            le.id == experience_id,
            le.status == "planificada",
            cs.class_id == le.class_id,
            cs.session_date == on,
            cs.deleted_at.is_(None),
        )
        .values(topic=None)
    )
    await sync_experience(conn, experience_id)


async def get_session_entry(conn: AsyncConnection, experience_id: UUID, on: date) -> dict[str, Any]:
    found = await list_experience_sessions(conn, experience_id, on)
    if not found:
        raise _session_entry_not_found()
    return found[0]
