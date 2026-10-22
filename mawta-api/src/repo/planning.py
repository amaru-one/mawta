"""Term planning, write side: experiences, criteria, planned evidences and the session outline.

Every domain rule the schema enforces at commit (the deferred triggers of migration 00002) or
with a raw Postgres error is checked here first, so the API answers with the contract's stable
codes instead. The constraints stay the last word; errors.map_error translates the two that only
concurrency can reach (experience overlap, one session entry per date).

Patches are dicts: a key is present only when the request set that field.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any, LiteralString
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

import domain
from db import fetch_all, fetch_one, fetch_required
from errors import AppError, NotFound
from repo.classctx import load_class_context
from repo.planning_plan import (
    class_dates,
    iso,
    term_evidence_by_competency,
)
from repo.planning_sync import sync_experience

# The least number of graded evidences a conclusion needs (see repo/conclusion_context.py).
MIN_CONCLUSION_EVIDENCES = 2

ISO_UTC = '\'YYYY-MM-DD"T"HH24:MI:SS"Z"\''

# Who wrote a planning row (proposed_by). A teacher's row is accepted when written; Mawta's
# stays pending (accepted_at null) until the teacher accepts or edits it.
BY_TEACHER = "teacher"
BY_MAWTA = "mawta"

# A numeric planned evidence's maximum when the teacher names none. Only a default.
DEFAULT_EVIDENCE_MAX_SCORE = 20.0


def bad_input(code: str, message: str) -> AppError:
    return AppError(400, code, message)


def unprocessable(code: str, message: str) -> AppError:
    return AppError(422, code, message)


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)


def dedupe(ids: list[UUID]) -> list[UUID]:
    """Drop repeated ids, keeping the first occurrence's order."""
    return list(dict.fromkeys(ids))


def trimmed_or_none(text: str | None) -> str | None:
    """Blank optional text becomes NULL."""
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


# ------------------------------------------------------------ experience --


async def get_experience(conn: AsyncConnection[DictRow], experience_id: UUID) -> dict[str, Any]:
    """The whole experience for the review, criteria, evidences, sessions and summary screens."""
    e = await fetch_required(
        conn,
        """
        select id, class_id, term_id, status, title, idea_text, situation_text, context_text,
               starts_on, ends_on
          from learning_experiences
         where id = %s and deleted_at is null
        """,
        (experience_id,),
    )
    competencies = await fetch_all(
        conn,
        """
        select c.id, c.code, c.name
          from experience_competencies ec
          join competencies c on c.id = ec.competency_id
         where ec.experience_id = %s and ec.deleted_at is null
         order by c.sort_order, c.code
        """,
        (experience_id,),
    )
    return {
        "id": e["id"],
        "class_id": e["class_id"],
        "term_id": e["term_id"],
        "status": e["status"],
        "title": e["title"],
        "idea_text": e["idea_text"],
        "situation_text": e["situation_text"],
        "context_text": e["context_text"],
        "starts_on": iso(e["starts_on"]),
        "ends_on": iso(e["ends_on"]),
        "competencies": competencies,
        "criteria": await list_experience_criteria(conn, experience_id),
        "evidences": await list_experience_evidences(conn, experience_id),
        "sessions": await list_experience_sessions(conn, experience_id),
        "class_dates": await class_dates(conn, e["class_id"], e["starts_on"], e["ends_on"]),
        "warnings": await _experience_warnings(conn, experience_id),
    }


async def list_experience_criteria(
    conn: AsyncConnection[DictRow], experience_id: UUID, criterion_id: UUID | None = None
) -> list[dict[str, Any]]:
    """The experience's criteria, or only one of them when criterion_id is set."""
    return await fetch_all(
        conn,
        f"""
        select cr.id, cr.experience_id, cr.competency_id, cr.description,
               coalesce((select array_agg(x.capability_id order by cap.sort_order, cap.code)
                           from evaluation_criterion_capabilities x
                           join capabilities cap on cap.id = x.capability_id
                          where x.criterion_id = cr.id and x.deleted_at is null),
                        '{{}}'::uuid[]) as capability_ids,
               cr.performance_id, cr.proposed_by,
               to_char(cr.accepted_at at time zone 'UTC', {ISO_UTC}) as accepted_at
          from evaluation_criteria cr
          join competencies c on c.id = cr.competency_id
         where cr.experience_id = %(exp)s and cr.deleted_at is null
           and (%(crit)s::uuid is null or cr.id = %(crit)s::uuid)
         order by c.sort_order, c.code, cr.sort_order, cr.created_at
        """,
        {"exp": experience_id, "crit": criterion_id},
    )


async def list_experience_evidences(
    conn: AsyncConnection[DictRow], experience_id: UUID, evidence_id: UUID | None = None
) -> list[dict[str, Any]]:
    """The experience's planned evidences, or only one of them when evidence_id is set."""
    rows = await fetch_all(
        conn,
        f"""
        select pe.id, pe.experience_id, pe.name, pe.kind, pe.value_scale, pe.max_score,
               coalesce((select array_agg(pc.criterion_id order by pc.created_at)
                           from planned_evidence_criteria pc
                          where pc.evidence_id = pe.id and pc.deleted_at is null),
                        '{{}}'::uuid[]) as criterion_ids,
               to_char(se.class_date, 'YYYY-MM-DD') as session_date, pe.proposed_by,
               to_char(pe.accepted_at at time zone 'UTC', {ISO_UTC}) as accepted_at
          from planned_evidences pe
          left join session_outline_entries se
                 on se.id = pe.session_entry_id and se.deleted_at is null
         where pe.experience_id = %(exp)s and pe.deleted_at is null
           and (%(ev)s::uuid is null or pe.id = %(ev)s::uuid)
         order by pe.created_at, pe.id
        """,
        {"exp": experience_id, "ev": evidence_id},
    )
    for r in rows:
        r["max_score"] = float(r["max_score"]) if r["max_score"] is not None else None
    return rows


async def list_experience_sessions(
    conn: AsyncConnection[DictRow], experience_id: UUID, on: date | None = None
) -> list[dict[str, Any]]:
    """The experience's session outline, or only the entry of one date when `on` is set."""
    return await fetch_all(
        conn,
        f"""
        select to_char(class_date, 'YYYY-MM-DD') as date, title, topics,
               planned_evidence_id, proposed_by,
               to_char(accepted_at at time zone 'UTC', {ISO_UTC}) as accepted_at
          from session_outline_entries
         where experience_id = %(exp)s and deleted_at is null
           and (%(on)s::date is null or class_date = %(on)s::date)
         order by class_date
        """,
        {"exp": experience_id, "on": on},
    )


async def _experience_warnings(
    conn: AsyncConnection[DictRow], experience_id: UUID
) -> list[dict[str, Any]]:
    """For every capability of the experience's competencies, the ones no accepted criterion looks
    at; then evidence-poor competencies; then how many proposals are still pending."""
    rows = await fetch_all(
        conn,
        """
        select c.id as competency_id, cap.id as capability_id
          from experience_competencies ec
          join competencies c on c.id = ec.competency_id
          join capabilities cap
            on cap.competency_id = c.id and cap.is_active and cap.deleted_at is null
         where ec.experience_id = %s and ec.deleted_at is null
           and not exists (
             select 1 from evaluation_criteria cr
               join evaluation_criterion_capabilities x
                 on x.criterion_id = cr.id and x.deleted_at is null
              where cr.experience_id = ec.experience_id and cr.deleted_at is null
                and cr.accepted_at is not null and x.capability_id = cap.id
           )
         order by c.sort_order, c.code, cap.sort_order, cap.code
        """,
        (experience_id,),
    )
    out: list[dict[str, Any]] = [
        {
            "code": "capability_without_criterion",
            "competency_id": r["competency_id"],
            "capability_id": r["capability_id"],
        }
        for r in rows
    ]

    # Evidence per competency is read over the whole term, not this experience: the conclusion
    # counts it that way, so a single experience is not an alarm.
    exp = await fetch_required(
        conn,
        "select class_id, term_id from learning_experiences where id = %s",
        (experience_id,),
    )
    tally = await term_evidence_by_competency(conn, exp["class_id"], exp["term_id"], False)
    comp_rows = await fetch_all(
        conn,
        """
        select ec.competency_id
          from experience_competencies ec
          join competencies c on c.id = ec.competency_id
         where ec.experience_id = %s and ec.deleted_at is null
         order by c.sort_order, c.code
        """,
        (experience_id,),
    )
    for r in comp_rows:
        t = tally.get(r["competency_id"], {"count": 0, "kinds": None})
        if t["count"] < MIN_CONCLUSION_EVIDENCES:
            out.append(
                {
                    "code": "competency_few_evidences",
                    "competency_id": r["competency_id"],
                    "count": t["count"],
                }
            )
        elif t["kinds"] is not None and len(t["kinds"]) == 1:
            out.append(
                {
                    "code": "competency_single_kind",
                    "competency_id": r["competency_id"],
                    "kind": t["kinds"][0],
                }
            )

    pending = (
        await fetch_required(
            conn,
            """
            select (select count(*) from evaluation_criteria
                     where experience_id = %(e)s and deleted_at is null and accepted_at is null)
                 + (select count(*) from planned_evidences
                     where experience_id = %(e)s and deleted_at is null and accepted_at is null)
                 + (select count(*) from session_outline_entries
                     where experience_id = %(e)s and deleted_at is null and accepted_at is null)
                   as n
            """,
            {"e": experience_id},
        )
    )["n"]
    if pending > 0:
        out.append({"code": "pending_proposals", "count": pending})
    return out


# ---------------------------------------------------------------- writes --


@dataclass
class ExperienceHeader:
    id: UUID
    class_id: UUID
    term_id: UUID
    status: str
    starts_on: date
    ends_on: date


async def lock_experience(conn: AsyncConnection[DictRow], experience_id: UUID) -> ExperienceHeader:
    """Read an experience and lock its row, so two edits of the same experience apply one after
    the other."""
    row = await fetch_one(
        conn,
        """
        select id, class_id, term_id, status, starts_on, ends_on
          from learning_experiences
         where id = %s and deleted_at is null
           for update
        """,
        (experience_id,),
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró la experiencia")
    return ExperienceHeader(**row)


async def _term_range(conn: AsyncConnection[DictRow], term_id: UUID) -> tuple[UUID, date, date]:
    row = await fetch_one(
        conn,
        "select academic_year_id, starts_on, ends_on from terms where id = %s and deleted_at is null",
        (term_id,),
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró el periodo")
    return row["academic_year_id"], row["starts_on"], row["ends_on"]


async def _check_experience_dates(
    conn: AsyncConnection[DictRow],
    class_id: UUID,
    experience_id: UUID | None,
    term_from: date,
    term_to: date,
    starts_on: date,
    ends_on: date,
) -> None:
    """A valid range, inside its term (check_inside_term), and not crossing another experience of
    the class, drafts included (learning_experiences_no_overlap)."""
    if ends_on < starts_on:
        raise bad_input("bad_request", "ends_on no puede ser anterior a starts_on")
    if starts_on < term_from or ends_on > term_to:
        raise unprocessable(
            "outside_term",
            "la experiencia debe empezar y terminar dentro del periodo"
            f" ({iso(term_from)} a {iso(term_to)})",
        )
    row = await fetch_required(
        conn,
        """
        select exists (
          select 1 from learning_experiences
           where class_id = %(class)s and id <> %(exp)s::uuid and deleted_at is null
             and daterange(starts_on, ends_on, '[]')
                 && daterange(%(from)s::date, %(to)s::date, '[]')
        ) as overlap
        """,
        {
            "class": class_id,
            "exp": experience_id or UUID(int=0),
            "from": starts_on,
            "to": ends_on,
        },
    )
    if row["overlap"]:
        raise conflict(
            "experience_overlap", "las fechas se cruzan con otra experiencia de esta clase"
        )


async def _check_competencies_in_subject(
    conn: AsyncConnection[DictRow], subject_id: UUID, ids: list[UUID]
) -> None:
    """Every competency must be an active competency of the class's área (check_competency_subject)."""
    row = await fetch_required(
        conn,
        """
        select count(*) as n from competencies
         where id = any(%s::uuid[]) and subject_id = %s and is_active and deleted_at is null
        """,
        (ids, subject_id),
    )
    if row["n"] != len(ids):
        raise unprocessable(
            "competency_not_in_subject", "esa competencia no es del área de esta clase"
        )


async def create_experience(
    conn: AsyncConnection[DictRow],
    class_id: UUID,
    *,
    term_id: UUID,
    title: str,
    idea_text: str,
    situation_text: str | None,
    context_text: str | None,
    starts_on: date,
    ends_on: date,
    competency_ids: list[UUID],
) -> UUID:
    """Create a draft experience with its competencies. Its academic year is the term's."""
    title = title.strip()
    if not title:
        raise bad_input("missing_title", "la experiencia necesita un título")
    idea = idea_text.strip()
    if not idea:
        raise bad_input("missing_idea", "la experiencia necesita la idea de la que nace")
    competency_ids = dedupe(competency_ids)
    if not competency_ids:
        raise bad_input("missing_competencies", "elige al menos una competencia")

    cc = await load_class_context(conn, class_id)
    year_id, term_from, term_to = await _term_range(conn, term_id)
    if year_id != cc["year_id"]:
        raise AppError(404, "not_found", "no se encontró el periodo")
    await _check_experience_dates(conn, class_id, None, term_from, term_to, starts_on, ends_on)
    await _check_competencies_in_subject(conn, cc["subject_id"], competency_ids)

    row = await fetch_required(
        conn,
        """
        insert into learning_experiences
          (tenant_id, class_id, academic_year_id, term_id, title, idea_text, situation_text,
           context_text, starts_on, ends_on)
        values (app.current_tenant_id(), %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (
            class_id,
            year_id,
            term_id,
            title,
            idea,
            trimmed_or_none(situation_text),
            trimmed_or_none(context_text),
            starts_on,
            ends_on,
        ),
    )
    await conn.execute(
        """
        insert into experience_competencies (tenant_id, experience_id, competency_id)
        select app.current_tenant_id(), %s, c from unnest(%s::uuid[]) as c
        """,
        (row["id"], competency_ids),
    )
    return row["id"]


async def update_experience(
    conn: AsyncConnection[DictRow], experience_id: UUID, patch: dict[str, Any]
) -> None:
    """Edit an experience. New dates must keep its session outline inside them; removing a
    competency that still has criteria is refused, so no criterion is ever left on a competency
    the experience no longer works. `patch` keys: title, situation_text, starts_on, ends_on,
    competency_ids (present only when set; an empty situation_text clears the situation)."""
    h = await lock_experience(conn, experience_id)
    if "title" in patch and not patch["title"].strip():
        raise bad_input("missing_title", "la experiencia necesita un título")

    starts_on = patch.get("starts_on") or h.starts_on
    ends_on = patch.get("ends_on") or h.ends_on
    if starts_on != h.starts_on or ends_on != h.ends_on:
        _, term_from, term_to = await _term_range(conn, h.term_id)
        await _check_experience_dates(
            conn, h.class_id, h.id, term_from, term_to, starts_on, ends_on
        )
        row = await fetch_required(
            conn,
            """
            select exists (
              select 1 from session_outline_entries
               where experience_id = %s and deleted_at is null
                 and class_date not between %s and %s
            ) as outside
            """,
            (h.id, starts_on, ends_on),
        )
        if row["outside"]:
            raise unprocessable(
                "date_not_in_experience",
                "hay sesiones planificadas fuera de las nuevas fechas; muévelas o elimínalas primero",
            )

    if "competency_ids" in patch:
        await _replace_experience_competencies(conn, h, dedupe(patch["competency_ids"]))

    title = patch["title"].strip() if "title" in patch else None
    situation_set = "situation_text" in patch
    await conn.execute(
        """
        update learning_experiences
           set title = coalesce(%(title)s::text, title),
               situation_text = case when %(set)s::bool then %(situation)s::text
                                     else situation_text end,
               starts_on = %(from)s, ends_on = %(to)s
         where id = %(id)s
        """,
        {
            "id": h.id,
            "title": title,
            "set": situation_set,
            "situation": trimmed_or_none(patch.get("situation_text")),
            "from": starts_on,
            "to": ends_on,
        },
    )


async def _replace_experience_competencies(
    conn: AsyncConnection[DictRow], h: ExperienceHeader, ids: list[UUID]
) -> None:
    if not ids:
        raise bad_input("missing_competencies", "elige al menos una competencia")
    cc = await load_class_context(conn, h.class_id)
    await _check_competencies_in_subject(conn, cc["subject_id"], ids)
    row = await fetch_required(
        conn,
        """
        select exists (
          select 1 from evaluation_criteria
           where experience_id = %s and deleted_at is null and not (competency_id = any(%s::uuid[]))
        ) as with_criteria
        """,
        (h.id, ids),
    )
    if row["with_criteria"]:
        raise conflict(
            "competency_has_criteria",
            "esa competencia todavía tiene criterios en esta experiencia; elimínalos primero",
        )
    await conn.execute(
        """
        update experience_competencies set deleted_at = now()
         where experience_id = %s and deleted_at is null and not (competency_id = any(%s::uuid[]))
        """,
        (h.id, ids),
    )
    await conn.execute(
        """
        insert into experience_competencies (tenant_id, experience_id, competency_id)
        select app.current_tenant_id(), %(exp)s, c from unnest(%(ids)s::uuid[]) as c
         where not exists (
           select 1 from experience_competencies ec
            where ec.experience_id = %(exp)s and ec.competency_id = c and ec.deleted_at is null
         )
        """,
        {"exp": h.id, "ids": ids},
    )


async def confirm_experience(conn: AsyncConnection[DictRow], experience_id: UUID) -> None:
    """ "Revisar y guardar": a draft becomes planned."""
    h = await lock_experience(conn, experience_id)
    if h.status != "borrador":
        raise conflict("experience_not_draft", "la experiencia ya está planificada")
    await conn.execute(
        "update learning_experiences set status = 'planificada' where id = %s", (h.id,)
    )
    await sync_experience(conn, h.id)


async def delete_experience(conn: AsyncConnection[DictRow], experience_id: UUID) -> None:
    """Soft-delete an experience with everything planned in it. The competency links go before the
    experience: check_competency_subject reads the live experience on every write to
    experience_competencies."""
    h = await lock_experience(conn, experience_id)
    statements: list[tuple[LiteralString, bool]] = [
        (
            """update assessments set deleted_at = now()
                where deleted_at is null
                  and planned_evidence_id in
                      (select id from planned_evidences where experience_id = %(e)s)""",
            False,
        ),
        (
            """update class_sessions cs set topic = null
                 from session_outline_entries e
                where e.experience_id = %(e)s and e.deleted_at is null
                  and cs.class_id = %(c)s and cs.session_date = e.class_date
                  and cs.topic = e.title""",
            True,
        ),
        (
            """update planned_evidence_criteria set deleted_at = now()
                where deleted_at is null
                  and evidence_id in
                      (select id from planned_evidences where experience_id = %(e)s)""",
            False,
        ),
        (
            """update evaluation_criterion_capabilities set deleted_at = now()
                where deleted_at is null
                  and criterion_id in
                      (select id from evaluation_criteria where experience_id = %(e)s)""",
            False,
        ),
        (
            "update evaluation_criteria set deleted_at = now()"
            " where experience_id = %(e)s and deleted_at is null",
            False,
        ),
        (
            "update planned_evidences set deleted_at = now()"
            " where experience_id = %(e)s and deleted_at is null",
            False,
        ),
        (
            "update session_outline_entries set deleted_at = now()"
            " where experience_id = %(e)s and deleted_at is null",
            False,
        ),
        (
            "update experience_competencies set deleted_at = now()"
            " where experience_id = %(e)s and deleted_at is null",
            False,
        ),
        ("update learning_experiences set deleted_at = now() where id = %(e)s", False),
    ]
    for sql, _ in statements:
        await conn.execute(sql, {"e": h.id, "c": h.class_id})


# -------------------------------------------------------------- criteria --


async def _check_criterion_competency(
    conn: AsyncConnection[DictRow], h: ExperienceHeader, competency_id: UUID
) -> None:
    """The competency must be one the experience works (check_criterion_experience)."""
    row = await fetch_required(
        conn,
        """
        select exists (
          select 1 from experience_competencies
           where experience_id = %s and competency_id = %s and deleted_at is null
        ) as ok
        """,
        (h.id, competency_id),
    )
    if row["ok"]:
        return
    cc = await load_class_context(conn, h.class_id)
    await _check_competencies_in_subject(conn, cc["subject_id"], [competency_id])
    raise unprocessable(
        "competency_not_in_experience",
        "esa competencia no está en esta experiencia; agrégala a la experiencia primero",
    )


async def _check_criterion_capabilities(
    conn: AsyncConnection[DictRow], competency_id: UUID, ids: list[UUID]
) -> None:
    """At least one capability, all of the criterion's competency
    (check_criterion_has_capability and the composite FK of evaluation_criterion_capabilities)."""
    if not ids:
        raise unprocessable("criterion_needs_capability", "un criterio mira al menos una capacidad")
    row = await fetch_required(
        conn,
        """
        select count(*) as n from capabilities
         where id = any(%s::uuid[]) and competency_id = %s and is_active and deleted_at is null
        """,
        (ids, competency_id),
    )
    if row["n"] != len(ids):
        raise unprocessable(
            "capability_not_in_competency", "esa capacidad no es de la competencia del criterio"
        )


async def _check_criterion_performance(
    conn: AsyncConnection[DictRow], class_id: UUID, competency_id: UUID, performance_id: UUID
) -> None:
    """The performance must be one of the competency's for the class's grade."""
    row = await fetch_required(
        conn,
        """
        select exists (
          select 1
            from grade_level_performances p
            join courses co on co.grade_level_id = p.grade_level_id
            join classes cl on cl.course_id = co.id
           where cl.id = %s and p.competency_id = %s and p.id = %s and p.deleted_at is null
        ) as ok
        """,
        (class_id, competency_id, performance_id),
    )
    if not row["ok"]:
        raise unprocessable(
            "performance_not_in_grade",
            "ese desempeño no es de esta competencia en el grado de la clase",
        )


async def create_planned_criterion(
    conn: AsyncConnection[DictRow], experience_id: UUID, inp: dict[str, Any], by: str = BY_TEACHER
) -> UUID:
    """Write a criterion for one of the experience's competencies, with its capabilities, in the
    same transaction: check_criterion_on_write fails the commit for a criterion without them.
    `inp` keys: competency_id, description, capability_ids, performance_id (optional: the standard
    is the main source of a criterion). by=BY_MAWTA is a proposal the planning agent makes; it
    passes the same checks and stays pending until the teacher accepts or edits it."""
    h = await lock_experience(conn, experience_id)
    description = inp["description"].strip()
    if not description:
        raise bad_input(
            "missing_description",
            "un criterio necesita una descripción: es contra lo que se lee la evidencia",
        )
    capability_ids = dedupe(inp["capability_ids"])
    competency_id = inp["competency_id"]
    await _check_criterion_competency(conn, h, competency_id)
    await _check_criterion_capabilities(conn, competency_id, capability_ids)
    performance_id = inp.get("performance_id")
    if performance_id is not None:
        await _check_criterion_performance(conn, h.class_id, competency_id, performance_id)

    row = await fetch_required(
        conn,
        """
        insert into evaluation_criteria
          (tenant_id, competency_id, description, sort_order, experience_id, performance_id,
           proposed_by, accepted_at)
        select app.current_tenant_id(), %(comp)s, %(desc)s, coalesce(max(sort_order), 0) + 1,
               %(exp)s, %(perf)s, %(by)s::text, case when %(by)s::text = 'teacher' then now() end
          from evaluation_criteria where experience_id = %(exp)s and deleted_at is null
        returning id
        """,
        {
            "comp": competency_id,
            "desc": description,
            "exp": h.id,
            "perf": performance_id,
            "by": by,
        },
    )
    await _set_criterion_capabilities(conn, row["id"], competency_id, capability_ids)
    return row["id"]


async def propose_criterion(
    conn: AsyncConnection[DictRow], experience_id: UUID, inp: dict[str, Any]
) -> UUID:
    return await create_planned_criterion(conn, experience_id, inp, BY_MAWTA)


async def _set_criterion_capabilities(
    conn: AsyncConnection[DictRow], criterion_id: UUID, competency_id: UUID, ids: list[UUID]
) -> None:
    """Make ids the criterion's whole capability list. competency_id is copied from the criterion,
    as check_criterion_capability_competency requires."""
    await conn.execute(
        """
        update evaluation_criterion_capabilities set deleted_at = now()
         where criterion_id = %s and deleted_at is null and not (capability_id = any(%s::uuid[]))
        """,
        (criterion_id, ids),
    )
    await conn.execute(
        """
        insert into evaluation_criterion_capabilities
               (tenant_id, criterion_id, competency_id, capability_id)
        select app.current_tenant_id(), %(crit)s, %(comp)s, c from unnest(%(ids)s::uuid[]) as c
         where not exists (
           select 1 from evaluation_criterion_capabilities x
            where x.criterion_id = %(crit)s and x.capability_id = c and x.deleted_at is null
         )
        """,
        {"crit": criterion_id, "comp": competency_id, "ids": ids},
    )


async def _lock_planned_criterion(
    conn: AsyncConnection[DictRow], criterion_id: UUID
) -> tuple[ExperienceHeader, UUID]:
    """Read a criterion of an experience and lock its experience. A global criterion is not part
    of any plan: not found."""
    row = await fetch_one(
        conn,
        """
        select experience_id, competency_id from evaluation_criteria
         where id = %s and experience_id is not null and deleted_at is null
        """,
        (criterion_id,),
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró el criterio")
    return await lock_experience(conn, row["experience_id"]), row["competency_id"]


async def update_planned_criterion(
    conn: AsyncConnection[DictRow], criterion_id: UUID, patch: dict[str, Any]
) -> None:
    """Edit a criterion; editing a proposal accepts it. `patch` keys: description,
    capability_ids, performance_id (a None value removes the performance)."""
    h, competency_id = await _lock_planned_criterion(conn, criterion_id)
    description = None
    if "description" in patch:
        description = patch["description"].strip()
        if not description:
            raise bad_input(
                "missing_description",
                "un criterio necesita una descripción: es contra lo que se lee la evidencia",
            )
    performance_set = "performance_id" in patch
    performance_id = patch.get("performance_id")
    if performance_set and performance_id is not None:
        await _check_criterion_performance(conn, h.class_id, competency_id, performance_id)
    if "capability_ids" in patch:
        ids = dedupe(patch["capability_ids"])
        await _check_criterion_capabilities(conn, competency_id, ids)
        await _set_criterion_capabilities(conn, criterion_id, competency_id, ids)
    await conn.execute(
        """
        update evaluation_criteria
           set description = coalesce(%(desc)s::text, description),
               performance_id = case when %(perf_set)s::bool then %(perf)s::uuid
                                     else performance_id end,
               accepted_at = coalesce(accepted_at, now())
         where id = %(id)s
        """,
        {
            "id": criterion_id,
            "desc": description,
            "perf_set": performance_set,
            "perf": performance_id,
        },
    )


async def accept_planned_criterion(conn: AsyncConnection[DictRow], criterion_id: UUID) -> None:
    """Accept a proposal unchanged. Accepting an accepted criterion is a no-op."""
    await _lock_planned_criterion(conn, criterion_id)
    await conn.execute(
        "update evaluation_criteria set accepted_at = coalesce(accepted_at, now()) where id = %s",
        (criterion_id,),
    )


async def get_planned_criterion(
    conn: AsyncConnection[DictRow], criterion_id: UUID
) -> dict[str, Any]:
    row = await fetch_required(
        conn,
        """
        select experience_id from evaluation_criteria
         where id = %s and experience_id is not null and deleted_at is null
        """,
        (criterion_id,),
    )
    found = await list_experience_criteria(conn, row["experience_id"], criterion_id)
    if not found:
        raise NotFound
    return found[0]


# ------------------------------------------------------------- evidences --


def resolve_evidence_scale(value_scale: str, max_score: float | None) -> tuple[str, float | None]:
    """Validate a scale and its maximum and fill in the default. A numeric evidence always ends
    with a maximum; an ordinal one never has one."""
    value_scale = value_scale or "numeric"
    if value_scale == "numeric":
        if max_score is None:
            return value_scale, DEFAULT_EVIDENCE_MAX_SCORE
        if max_score <= 0:
            raise bad_input("bad_request", "max_score debe ser mayor que 0")
        return value_scale, max_score
    if value_scale == "ordinal":
        if max_score is not None:
            raise bad_input("bad_request", "una evidencia ordinal (AD/A/B/C) no lleva max_score")
        return value_scale, None
    raise bad_input("bad_request", "value_scale debe ser numeric u ordinal")


def check_evidence_kind(kind: str) -> None:
    if not domain.is_evidence_kind(kind):
        raise bad_input("bad_request", "kind debe ser produccion o actuacion")


async def check_evidence_criteria(
    conn: AsyncConnection[DictRow], experience_id: UUID, ids: list[UUID]
) -> None:
    """At least one criterion, all of this experience (check_evidence_criterion_experience).
    They may come from any of its competencies."""
    if not ids:
        raise bad_input("missing_criteria", "una evidencia observa al menos un criterio")
    row = await fetch_required(
        conn,
        """
        select count(*) as n from evaluation_criteria
         where id = any(%s::uuid[]) and experience_id = %s and deleted_at is null
        """,
        (ids, experience_id),
    )
    if row["n"] != len(ids):
        raise unprocessable("criterion_other_experience", "ese criterio no es de esta experiencia")


async def session_entry_at(conn: AsyncConnection[DictRow], experience_id: UUID, on: date) -> UUID:
    """The experience's session entry of a date, which a placed evidence needs."""
    row = await fetch_one(
        conn,
        """
        select id from session_outline_entries
         where experience_id = %s and class_date = %s and deleted_at is null
        """,
        (experience_id, on),
    )
    if row is None:
        raise unprocessable(
            "date_not_in_experience", "no hay una sesión planificada en esa fecha de la experiencia"
        )
    return row["id"]


async def place_evidence(
    conn: AsyncConnection[DictRow], evidence_id: UUID, entry_id: UUID | None
) -> None:
    """Set where an evidence is collected, keeping both sides of the relation in step:
    planned_evidences.session_entry_id and session_outline_entries.planned_evidence_id. A session
    holds one evidence, so placing an evidence in a session unplaces the one that was there."""
    await conn.execute(
        """
        update session_outline_entries set planned_evidence_id = null
         where planned_evidence_id = %(ev)s and deleted_at is null
           and (%(entry)s::uuid is null or id <> %(entry)s::uuid)
        """,
        {"ev": evidence_id, "entry": entry_id},
    )
    if entry_id is not None:
        await conn.execute(
            """
            update planned_evidences set session_entry_id = null
             where session_entry_id = %s and id <> %s
            """,
            (entry_id, evidence_id),
        )
        await conn.execute(
            "update session_outline_entries set planned_evidence_id = %s where id = %s",
            (evidence_id, entry_id),
        )
    await conn.execute(
        "update planned_evidences set session_entry_id = %s where id = %s", (entry_id, evidence_id)
    )


async def unplace_entry(conn: AsyncConnection[DictRow], entry_id: UUID) -> None:
    """Empty a session entry and unplace the evidence it held."""
    await conn.execute(
        "update planned_evidences set session_entry_id = null where session_entry_id = %s",
        (entry_id,),
    )
    await conn.execute(
        """
        update session_outline_entries set planned_evidence_id = null
         where id = %s and planned_evidence_id is not null
        """,
        (entry_id,),
    )


async def set_evidence_criteria(
    conn: AsyncConnection[DictRow], evidence_id: UUID, ids: list[UUID]
) -> None:
    await conn.execute(
        """
        update planned_evidence_criteria set deleted_at = now()
         where evidence_id = %s and deleted_at is null and not (criterion_id = any(%s::uuid[]))
        """,
        (evidence_id, ids),
    )
    await conn.execute(
        """
        insert into planned_evidence_criteria (tenant_id, evidence_id, criterion_id)
        select app.current_tenant_id(), %(ev)s, c from unnest(%(ids)s::uuid[]) as c
         where not exists (
           select 1 from planned_evidence_criteria pc
            where pc.evidence_id = %(ev)s and pc.criterion_id = c and pc.deleted_at is null
         )
        """,
        {"ev": evidence_id, "ids": ids},
    )


async def create_planned_evidence(
    conn: AsyncConnection[DictRow], experience_id: UUID, inp: dict[str, Any], by: str = BY_TEACHER
) -> UUID:
    """Write a planned evidence, optionally placed in the session entry of `session_date`.
    `inp` keys: name, kind, value_scale, max_score, criterion_ids, session_date. A teacher's
    evidence syncs the experience; by=BY_MAWTA is a proposal that stays pending."""
    h = await lock_experience(conn, experience_id)
    name = inp["name"].strip()
    if not name:
        raise bad_input("missing_name", "la evidencia necesita un nombre")
    check_evidence_kind(inp["kind"])
    value_scale, max_score = resolve_evidence_scale(
        inp.get("value_scale", ""), inp.get("max_score")
    )
    criterion_ids = dedupe(inp["criterion_ids"])
    await check_evidence_criteria(conn, h.id, criterion_ids)
    entry_id = None
    if inp.get("session_date") is not None:
        entry_id = await session_entry_at(conn, h.id, inp["session_date"])

    row = await fetch_required(
        conn,
        """
        insert into planned_evidences (tenant_id, experience_id, name, kind, value_scale, max_score,
                                       proposed_by, accepted_at)
        values (app.current_tenant_id(), %(exp)s, %(name)s, %(kind)s, %(scale)s, %(max)s,
                %(by)s::text, case when %(by)s::text = 'teacher' then now() end)
        returning id
        """,
        {
            "exp": h.id,
            "name": name,
            "kind": inp["kind"],
            "scale": value_scale,
            "max": max_score,
            "by": by,
        },
    )
    evidence_id = row["id"]
    await set_evidence_criteria(conn, evidence_id, criterion_ids)
    if entry_id is not None:
        await place_evidence(conn, evidence_id, entry_id)
    if by == BY_TEACHER:
        await sync_experience(conn, experience_id)
    return evidence_id


async def propose_evidence(
    conn: AsyncConnection[DictRow], experience_id: UUID, inp: dict[str, Any]
) -> UUID:
    return await create_planned_evidence(conn, experience_id, inp, BY_MAWTA)
