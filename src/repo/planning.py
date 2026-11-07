"""Term planning, write side: experiences, criteria, planned evidences and the session outline.

Every domain rule the schema enforces at commit (the deferred triggers) or with a raw Postgres
error is checked here first, so the API answers with the contract's stable codes instead. The
constraints stay the last word; errors.map_error translates the two that only concurrency can
reach (experience overlap, one session entry per date).

Patches are dicts: a key is present only when the request set that field.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Text,
    case,
    func,
    insert,
    literal,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection

import domain
from db import fetch_all, fetch_one, fetch_required, scalar
from errors import AppError, NotFound
from mawta_schema.tables import (
    Assessment,
    Capability,
    Class,
    ClassSession,
    Competency,
    Course,
    EvaluationCriterion,
    EvaluationCriterionCapability,
    ExperienceCompetency,
    GradeLevelPerformance,
    LearningExperience,
    PlannedEvidence,
    PlannedEvidenceCriterion,
    SessionOutlineEntry,
    Term,
)
from repo.classctx import load_class_context
from repo.planning_plan import (
    class_dates,
    iso,
    term_evidence_by_competency,
)
from repo.planning_sync import sync_experience

# The least number of graded evidences a conclusion needs (see repo/conclusion_context.py).
MIN_CONCLUSION_EVIDENCES = 2

# Who wrote a planning row (proposed_by). A teacher's row is accepted when written; Mawta's
# stays pending (accepted_at null) until the teacher accepts or edits it.
BY_TEACHER = "teacher"
BY_MAWTA = "mawta"

# A numeric planned evidence's maximum when the teacher names none. Only a default.
DEFAULT_EVIDENCE_MAX_SCORE = 20.0


_UUIDS = ARRAY(PgUUID(as_uuid=True))


def iso_utc(column: Any) -> Any:
    """A timestamp as the API writes it: RFC 3339 in UTC, to the second."""
    return func.to_char(func.timezone("UTC", column), 'YYYY-MM-DD"T"HH24:MI:SS"Z"')


def _ids_table(ids: list[UUID]):
    """A list of ids as a table, u(c), to insert the ones missing from a link table."""
    return func.unnest(literal(ids, _UUIDS)).table_valued("c").render_derived(name="u")


async def _exists(conn: AsyncConnection, *where: ColumnElement[bool]) -> bool:
    return await scalar(conn, select(select(1).where(*where).exists()))


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


async def get_experience(conn: AsyncConnection, experience_id: UUID) -> dict[str, Any]:
    """The whole experience for the review, criteria, evidences, sessions and summary screens."""
    le = LearningExperience
    e = await fetch_required(
        conn,
        select(
            le.id,
            le.class_id,
            le.term_id,
            le.status,
            le.title,
            le.idea_text,
            le.situation_text,
            le.context_text,
            le.starts_on,
            le.ends_on,
        ).where(le.id == experience_id, le.deleted_at.is_(None)),
    )
    competencies = await fetch_all(
        conn,
        select(Competency.id, Competency.code, Competency.name)
        .select_from(ExperienceCompetency)
        .join(Competency, Competency.id == ExperienceCompetency.competency_id)
        .where(
            ExperienceCompetency.experience_id == experience_id,
            ExperienceCompetency.deleted_at.is_(None),
        )
        .order_by(Competency.sort_order, Competency.code),
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
        "competencies": [dict(c) for c in competencies],
        "criteria": await list_experience_criteria(conn, experience_id),
        "evidences": await list_experience_evidences(conn, experience_id),
        "sessions": await list_experience_sessions(conn, experience_id),
        "class_dates": await class_dates(conn, e["class_id"], e["starts_on"], e["ends_on"]),
        "warnings": await _experience_warnings(conn, experience_id),
    }


async def list_experience_criteria(
    conn: AsyncConnection, experience_id: UUID, criterion_id: UUID | None = None
) -> list[dict[str, Any]]:
    """The experience's criteria, or only one of them when criterion_id is set."""
    cr, x = EvaluationCriterion, EvaluationCriterionCapability
    capability_ids = (
        select(
            func.array_agg(
                aggregate_order_by(x.capability_id, Capability.sort_order, Capability.code)
            )
        )
        .select_from(x)
        .join(Capability, Capability.id == x.capability_id)
        .where(x.criterion_id == cr.id, x.deleted_at.is_(None))
        .scalar_subquery()
    )
    only = [] if criterion_id is None else [cr.id == criterion_id]
    rows = await fetch_all(
        conn,
        select(
            cr.id,
            cr.experience_id,
            cr.competency_id,
            cr.description,
            func.coalesce(capability_ids, literal([], _UUIDS)).label("capability_ids"),
            cr.performance_id,
            cr.proposed_by,
            iso_utc(cr.accepted_at).label("accepted_at"),
        )
        .join(Competency, Competency.id == cr.competency_id)
        .where(cr.experience_id == experience_id, cr.deleted_at.is_(None), *only)
        .order_by(Competency.sort_order, Competency.code, cr.sort_order, cr.created_at),
    )
    return [dict(r) for r in rows]


async def list_experience_evidences(
    conn: AsyncConnection, experience_id: UUID, evidence_id: UUID | None = None
) -> list[dict[str, Any]]:
    """The experience's planned evidences, or only one of them when evidence_id is set."""
    pe, pc, se = PlannedEvidence, PlannedEvidenceCriterion, SessionOutlineEntry
    criterion_ids = (
        # criterion_id breaks the tie: the links of one evidence are written in one statement.
        select(func.array_agg(aggregate_order_by(pc.criterion_id, pc.created_at, pc.criterion_id)))
        .where(pc.evidence_id == pe.id, pc.deleted_at.is_(None))
        .scalar_subquery()
    )
    only = [] if evidence_id is None else [pe.id == evidence_id]
    rows = await fetch_all(
        conn,
        select(
            pe.id,
            pe.experience_id,
            pe.name,
            pe.kind,
            pe.value_scale,
            pe.max_score,
            func.coalesce(criterion_ids, literal([], _UUIDS)).label("criterion_ids"),
            func.to_char(se.class_date, "YYYY-MM-DD").label("session_date"),
            pe.proposed_by,
            iso_utc(pe.accepted_at).label("accepted_at"),
        )
        .outerjoin(se, (se.id == pe.session_entry_id) & se.deleted_at.is_(None))
        .where(pe.experience_id == experience_id, pe.deleted_at.is_(None), *only)
        .order_by(pe.created_at, pe.id),
    )
    out = [dict(r) for r in rows]
    for r in out:
        r["max_score"] = float(r["max_score"]) if r["max_score"] is not None else None
    return out


async def list_experience_sessions(
    conn: AsyncConnection, experience_id: UUID, on: date | None = None
) -> list[dict[str, Any]]:
    """The experience's session outline, or only the entry of one date when `on` is set."""
    se = SessionOutlineEntry
    only = [] if on is None else [se.class_date == on]
    rows = await fetch_all(
        conn,
        select(
            func.to_char(se.class_date, "YYYY-MM-DD").label("date"),
            se.title,
            se.topics,
            se.planned_evidence_id,
            se.proposed_by,
            iso_utc(se.accepted_at).label("accepted_at"),
        )
        .where(se.experience_id == experience_id, se.deleted_at.is_(None), *only)
        .order_by(se.class_date),
    )
    return [dict(r) for r in rows]


async def _experience_warnings(conn: AsyncConnection, experience_id: UUID) -> list[dict[str, Any]]:
    """For every capability of the experience's competencies, the ones no accepted criterion looks
    at; then evidence-poor competencies; then how many proposals are still pending."""
    ec, cr, x = ExperienceCompetency, EvaluationCriterion, EvaluationCriterionCapability
    looked_at = (
        select(1)
        .select_from(cr)
        .join(x, (x.criterion_id == cr.id) & x.deleted_at.is_(None))
        .where(
            cr.experience_id == ec.experience_id,
            cr.deleted_at.is_(None),
            cr.accepted_at.is_not(None),
            x.capability_id == Capability.id,
        )
        .exists()
    )
    rows = await fetch_all(
        conn,
        select(Competency.id.label("competency_id"), Capability.id.label("capability_id"))
        .select_from(ec)
        .join(Competency, Competency.id == ec.competency_id)
        .join(
            Capability,
            (Capability.competency_id == Competency.id)
            & Capability.is_active
            & Capability.deleted_at.is_(None),
        )
        .where(ec.experience_id == experience_id, ec.deleted_at.is_(None), ~looked_at)
        .order_by(Competency.sort_order, Competency.code, Capability.sort_order, Capability.code),
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
        select(LearningExperience.class_id, LearningExperience.term_id).where(
            LearningExperience.id == experience_id
        ),
    )
    tally = await term_evidence_by_competency(conn, exp["class_id"], exp["term_id"], False)
    comp_rows = await fetch_all(
        conn,
        select(ec.competency_id)
        .join(Competency, Competency.id == ec.competency_id)
        .where(ec.experience_id == experience_id, ec.deleted_at.is_(None))
        .order_by(Competency.sort_order, Competency.code),
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

    def unaccepted(model: Any) -> Any:
        return (
            select(func.count())
            .where(
                model.experience_id == experience_id,
                model.deleted_at.is_(None),
                model.accepted_at.is_(None),
            )
            .scalar_subquery()
        )

    pending = await scalar(
        conn,
        select(
            unaccepted(EvaluationCriterion)
            + unaccepted(PlannedEvidence)
            + unaccepted(SessionOutlineEntry)
        ),
    )
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


async def lock_experience(conn: AsyncConnection, experience_id: UUID) -> ExperienceHeader:
    """Read an experience and lock its row, so two edits of the same experience apply one after
    the other."""
    le = LearningExperience
    row = await fetch_one(
        conn,
        select(le.id, le.class_id, le.term_id, le.status, le.starts_on, le.ends_on)
        .where(le.id == experience_id, le.deleted_at.is_(None))
        .with_for_update(),
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró la experiencia")
    return ExperienceHeader(**row)


async def _term_range(conn: AsyncConnection, term_id: UUID) -> tuple[UUID, date, date]:
    row = await fetch_one(
        conn,
        select(Term.academic_year_id, Term.starts_on, Term.ends_on).where(
            Term.id == term_id, Term.deleted_at.is_(None)
        ),
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró el periodo")
    return row["academic_year_id"], row["starts_on"], row["ends_on"]


async def _check_experience_dates(
    conn: AsyncConnection,
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
    le = LearningExperience
    overlap = await _exists(
        conn,
        le.class_id == class_id,
        le.id != (experience_id or UUID(int=0)),
        le.deleted_at.is_(None),
        func.daterange(le.starts_on, le.ends_on, "[]").op("&&")(
            func.daterange(starts_on, ends_on, "[]")
        ),
    )
    if overlap:
        raise conflict(
            "experience_overlap", "las fechas se cruzan con otra experiencia de esta clase"
        )


async def _check_competencies_in_subject(
    conn: AsyncConnection, subject_id: UUID, ids: list[UUID]
) -> None:
    """Every competency must be an active competency of the class's área (check_competency_subject)."""
    n = await scalar(
        conn,
        select(func.count()).where(
            Competency.id.in_(ids),
            Competency.subject_id == subject_id,
            Competency.is_active,
            Competency.deleted_at.is_(None),
        ),
    )
    if n != len(ids):
        raise unprocessable(
            "competency_not_in_subject", "esa competencia no es del área de esta clase"
        )


async def _link_competencies(conn: AsyncConnection, experience_id: UUID, ids: list[UUID]) -> None:
    """Add the experience_competencies rows that are not live yet."""
    ec, u = ExperienceCompetency, _ids_table(ids)
    missing = (
        select(1)
        .where(
            ec.experience_id == experience_id, ec.competency_id == u.c.c, ec.deleted_at.is_(None)
        )
        .exists()
    )
    await conn.execute(
        insert(ec).from_select(
            ["experience_id", "competency_id"],
            select(literal(experience_id, ec.experience_id.type), u.c.c)
            .select_from(u)
            .where(~missing),
        )
    )


async def create_experience(
    conn: AsyncConnection,
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

    experience_id = await scalar(
        conn,
        insert(LearningExperience)
        .values(
            class_id=class_id,
            academic_year_id=year_id,
            term_id=term_id,
            title=title,
            idea_text=idea,
            situation_text=trimmed_or_none(situation_text),
            context_text=trimmed_or_none(context_text),
            starts_on=starts_on,
            ends_on=ends_on,
        )
        .returning(LearningExperience.id),
    )
    await conn.execute(
        insert(ExperienceCompetency).values(
            [{"experience_id": experience_id, "competency_id": c} for c in competency_ids]
        )
    )
    return experience_id


async def update_experience(
    conn: AsyncConnection, experience_id: UUID, patch: dict[str, Any]
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
        se = SessionOutlineEntry
        outside = await _exists(
            conn,
            se.experience_id == h.id,
            se.deleted_at.is_(None),
            ~se.class_date.between(starts_on, ends_on),
        )
        if outside:
            raise unprocessable(
                "date_not_in_experience",
                "hay sesiones planificadas fuera de las nuevas fechas; muévelas o elimínalas primero",
            )

    if "competency_ids" in patch:
        await _replace_experience_competencies(conn, h, dedupe(patch["competency_ids"]))

    values: dict[str, Any] = {"starts_on": starts_on, "ends_on": ends_on}
    if "title" in patch:
        values["title"] = patch["title"].strip()
    if "situation_text" in patch:
        values["situation_text"] = trimmed_or_none(patch["situation_text"])
    await conn.execute(
        update(LearningExperience).where(LearningExperience.id == h.id).values(**values)
    )


async def _replace_experience_competencies(
    conn: AsyncConnection, h: ExperienceHeader, ids: list[UUID]
) -> None:
    if not ids:
        raise bad_input("missing_competencies", "elige al menos una competencia")
    cc = await load_class_context(conn, h.class_id)
    await _check_competencies_in_subject(conn, cc["subject_id"], ids)
    cr = EvaluationCriterion
    with_criteria = await _exists(
        conn, cr.experience_id == h.id, cr.deleted_at.is_(None), ~cr.competency_id.in_(ids)
    )
    if with_criteria:
        raise conflict(
            "competency_has_criteria",
            "esa competencia todavía tiene criterios en esta experiencia; elimínalos primero",
        )
    ec = ExperienceCompetency
    await conn.execute(
        update(ec)
        .where(ec.experience_id == h.id, ec.deleted_at.is_(None), ~ec.competency_id.in_(ids))
        .values(deleted_at=func.now())
    )
    await _link_competencies(conn, h.id, ids)


async def confirm_experience(conn: AsyncConnection, experience_id: UUID) -> None:
    """ "Revisar y guardar": a draft becomes planned."""
    h = await lock_experience(conn, experience_id)
    if h.status != "borrador":
        raise conflict("experience_not_draft", "la experiencia ya está planificada")
    await conn.execute(
        update(LearningExperience).where(LearningExperience.id == h.id).values(status="planificada")
    )
    await sync_experience(conn, h.id)


def _soft_delete(model: Any, *where: ColumnElement[bool]) -> Any:
    return update(model).where(model.deleted_at.is_(None), *where).values(deleted_at=func.now())


async def delete_experience(conn: AsyncConnection, experience_id: UUID) -> None:
    """Soft-delete an experience with everything planned in it. The competency links go before the
    experience: check_competency_subject reads the live experience on every write to
    experience_competencies."""
    h = await lock_experience(conn, experience_id)
    e = h.id
    evidences = select(PlannedEvidence.id).where(PlannedEvidence.experience_id == e)
    criteria = select(EvaluationCriterion.id).where(EvaluationCriterion.experience_id == e)
    se, cs = SessionOutlineEntry, ClassSession
    for stmt in (
        _soft_delete(Assessment, Assessment.planned_evidence_id.in_(evidences)),
        # The topic a session got from this experience's outline goes with it.
        update(cs)
        .where(
            se.experience_id == e,
            se.deleted_at.is_(None),
            cs.class_id == h.class_id,
            cs.session_date == se.class_date,
            cs.topic == se.title,
        )
        .values(topic=None),
        _soft_delete(PlannedEvidenceCriterion, PlannedEvidenceCriterion.evidence_id.in_(evidences)),
        _soft_delete(
            EvaluationCriterionCapability,
            EvaluationCriterionCapability.criterion_id.in_(criteria),
        ),
        _soft_delete(EvaluationCriterion, EvaluationCriterion.experience_id == e),
        _soft_delete(PlannedEvidence, PlannedEvidence.experience_id == e),
        _soft_delete(SessionOutlineEntry, SessionOutlineEntry.experience_id == e),
        _soft_delete(ExperienceCompetency, ExperienceCompetency.experience_id == e),
        update(LearningExperience).where(LearningExperience.id == e).values(deleted_at=func.now()),
    ):
        await conn.execute(stmt)


# -------------------------------------------------------------- criteria --


async def _check_criterion_competency(
    conn: AsyncConnection, h: ExperienceHeader, competency_id: UUID
) -> None:
    """The competency must be one the experience works (check_criterion_experience)."""
    ec = ExperienceCompetency
    if await _exists(
        conn,
        ec.experience_id == h.id,
        ec.competency_id == competency_id,
        ec.deleted_at.is_(None),
    ):
        return
    cc = await load_class_context(conn, h.class_id)
    await _check_competencies_in_subject(conn, cc["subject_id"], [competency_id])
    raise unprocessable(
        "competency_not_in_experience",
        "esa competencia no está en esta experiencia; agrégala a la experiencia primero",
    )


async def _check_criterion_capabilities(
    conn: AsyncConnection, competency_id: UUID, ids: list[UUID]
) -> None:
    """At least one capability, all of the criterion's competency
    (check_criterion_has_capability and the composite FK of evaluation_criterion_capabilities)."""
    if not ids:
        raise unprocessable("criterion_needs_capability", "un criterio mira al menos una capacidad")
    n = await scalar(
        conn,
        select(func.count()).where(
            Capability.id.in_(ids),
            Capability.competency_id == competency_id,
            Capability.is_active,
            Capability.deleted_at.is_(None),
        ),
    )
    if n != len(ids):
        raise unprocessable(
            "capability_not_in_competency", "esa capacidad no es de la competencia del criterio"
        )


async def _check_criterion_performance(
    conn: AsyncConnection, class_id: UUID, competency_id: UUID, performance_id: UUID
) -> None:
    """The performance must be one of the competency's for the class's grade."""
    p = GradeLevelPerformance
    ok = await scalar(
        conn,
        select(
            select(1)
            .select_from(p)
            .join(Course, Course.grade_level_id == p.grade_level_id)
            .join(Class, Class.course_id == Course.id)
            .where(
                Class.id == class_id,
                p.competency_id == competency_id,
                p.id == performance_id,
                p.deleted_at.is_(None),
            )
            .exists()
        ),
    )
    if not ok:
        raise unprocessable(
            "performance_not_in_grade",
            "ese desempeño no es de esta competencia en el grado de la clase",
        )


def _accepted_if_teacher(by: str) -> Any:
    """A teacher's row is accepted when written; Mawta's stays pending."""
    return case((literal(by, Text) == BY_TEACHER, func.now()))


async def create_planned_criterion(
    conn: AsyncConnection, experience_id: UUID, inp: dict[str, Any], by: str = BY_TEACHER
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

    cr = EvaluationCriterion
    columns = {
        "competency_id": literal(competency_id, cr.competency_id.type),
        "description": literal(description, cr.description.type),
        "sort_order": func.coalesce(func.max(cr.sort_order), 0) + 1,
        "experience_id": literal(h.id, cr.experience_id.type),
        "performance_id": literal(performance_id, cr.performance_id.type),
        "proposed_by": literal(by, cr.proposed_by.type),
        "accepted_at": _accepted_if_teacher(by),
    }
    criterion_id = await scalar(
        conn,
        insert(cr)
        .from_select(
            list(columns),
            select(*columns.values()).where(cr.experience_id == h.id, cr.deleted_at.is_(None)),
        )
        .returning(cr.id),
    )
    await _set_criterion_capabilities(conn, criterion_id, competency_id, capability_ids)
    return criterion_id


async def propose_criterion(
    conn: AsyncConnection, experience_id: UUID, inp: dict[str, Any]
) -> UUID:
    return await create_planned_criterion(conn, experience_id, inp, BY_MAWTA)


async def _set_criterion_capabilities(
    conn: AsyncConnection, criterion_id: UUID, competency_id: UUID, ids: list[UUID]
) -> None:
    """Make ids the criterion's whole capability list. competency_id is copied from the criterion,
    as check_criterion_capability_competency requires."""
    x = EvaluationCriterionCapability
    await conn.execute(_soft_delete(x, x.criterion_id == criterion_id, ~x.capability_id.in_(ids)))
    u = _ids_table(ids)
    linked = (
        select(1)
        .where(x.criterion_id == criterion_id, x.capability_id == u.c.c, x.deleted_at.is_(None))
        .exists()
    )
    await conn.execute(
        insert(x).from_select(
            ["criterion_id", "competency_id", "capability_id"],
            select(
                literal(criterion_id, x.criterion_id.type),
                literal(competency_id, x.competency_id.type),
                u.c.c,
            )
            .select_from(u)
            .where(~linked),
        )
    )


async def _lock_planned_criterion(
    conn: AsyncConnection, criterion_id: UUID
) -> tuple[ExperienceHeader, UUID]:
    """Read a criterion of an experience and lock its experience. A global criterion is not part
    of any plan: not found."""
    cr = EvaluationCriterion
    row = await fetch_one(
        conn,
        select(cr.experience_id, cr.competency_id).where(
            cr.id == criterion_id, cr.experience_id.is_not(None), cr.deleted_at.is_(None)
        ),
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró el criterio")
    return await lock_experience(conn, row["experience_id"]), row["competency_id"]


async def update_planned_criterion(
    conn: AsyncConnection, criterion_id: UUID, patch: dict[str, Any]
) -> None:
    """Edit a criterion; editing a proposal accepts it. `patch` keys: description,
    capability_ids, performance_id (a None value removes the performance)."""
    h, competency_id = await _lock_planned_criterion(conn, criterion_id)
    cr = EvaluationCriterion
    values: dict[str, Any] = {"accepted_at": func.coalesce(cr.accepted_at, func.now())}
    if "description" in patch:
        description = patch["description"].strip()
        if not description:
            raise bad_input(
                "missing_description",
                "un criterio necesita una descripción: es contra lo que se lee la evidencia",
            )
        values["description"] = description
    if "performance_id" in patch:
        performance_id = patch["performance_id"]
        if performance_id is not None:
            await _check_criterion_performance(conn, h.class_id, competency_id, performance_id)
        values["performance_id"] = performance_id
    if "capability_ids" in patch:
        ids = dedupe(patch["capability_ids"])
        await _check_criterion_capabilities(conn, competency_id, ids)
        await _set_criterion_capabilities(conn, criterion_id, competency_id, ids)
    await conn.execute(update(cr).where(cr.id == criterion_id).values(**values))


async def accept_planned_criterion(conn: AsyncConnection, criterion_id: UUID) -> None:
    """Accept a proposal unchanged. Accepting an accepted criterion is a no-op."""
    await _lock_planned_criterion(conn, criterion_id)
    cr = EvaluationCriterion
    await conn.execute(
        update(cr)
        .where(cr.id == criterion_id)
        .values(accepted_at=func.coalesce(cr.accepted_at, func.now()))
    )


async def get_planned_criterion(conn: AsyncConnection, criterion_id: UUID) -> dict[str, Any]:
    cr = EvaluationCriterion
    row = await fetch_required(
        conn,
        select(cr.experience_id).where(
            cr.id == criterion_id, cr.experience_id.is_not(None), cr.deleted_at.is_(None)
        ),
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
    conn: AsyncConnection, experience_id: UUID, ids: list[UUID]
) -> None:
    """At least one criterion, all of this experience (check_evidence_criterion_experience).
    They may come from any of its competencies."""
    if not ids:
        raise bad_input("missing_criteria", "una evidencia observa al menos un criterio")
    cr = EvaluationCriterion
    n = await scalar(
        conn,
        select(func.count()).where(
            cr.id.in_(ids), cr.experience_id == experience_id, cr.deleted_at.is_(None)
        ),
    )
    if n != len(ids):
        raise unprocessable("criterion_other_experience", "ese criterio no es de esta experiencia")


async def session_entry_at(conn: AsyncConnection, experience_id: UUID, on: date) -> UUID:
    """The experience's session entry of a date, which a placed evidence needs."""
    se = SessionOutlineEntry
    row = await fetch_one(
        conn,
        select(se.id).where(
            se.experience_id == experience_id, se.class_date == on, se.deleted_at.is_(None)
        ),
    )
    if row is None:
        raise unprocessable(
            "date_not_in_experience", "no hay una sesión planificada en esa fecha de la experiencia"
        )
    return row["id"]


async def place_evidence(conn: AsyncConnection, evidence_id: UUID, entry_id: UUID | None) -> None:
    """Set where an evidence is collected, keeping both sides of the relation in step:
    planned_evidences.session_entry_id and session_outline_entries.planned_evidence_id. A session
    holds one evidence, so placing an evidence in a session unplaces the one that was there."""
    se, pe = SessionOutlineEntry, PlannedEvidence
    other_entry = [] if entry_id is None else [se.id != entry_id]
    await conn.execute(
        update(se)
        .where(se.planned_evidence_id == evidence_id, se.deleted_at.is_(None), *other_entry)
        .values(planned_evidence_id=None)
    )
    if entry_id is not None:
        await conn.execute(
            update(pe)
            .where(pe.session_entry_id == entry_id, pe.id != evidence_id)
            .values(session_entry_id=None)
        )
        await conn.execute(
            update(se).where(se.id == entry_id).values(planned_evidence_id=evidence_id)
        )
    await conn.execute(update(pe).where(pe.id == evidence_id).values(session_entry_id=entry_id))


async def unplace_entry(conn: AsyncConnection, entry_id: UUID) -> None:
    """Empty a session entry and unplace the evidence it held."""
    se, pe = SessionOutlineEntry, PlannedEvidence
    await conn.execute(
        update(pe).where(pe.session_entry_id == entry_id).values(session_entry_id=None)
    )
    await conn.execute(
        update(se)
        .where(se.id == entry_id, se.planned_evidence_id.is_not(None))
        .values(planned_evidence_id=None)
    )


async def set_evidence_criteria(conn: AsyncConnection, evidence_id: UUID, ids: list[UUID]) -> None:
    pc = PlannedEvidenceCriterion
    await conn.execute(_soft_delete(pc, pc.evidence_id == evidence_id, ~pc.criterion_id.in_(ids)))
    u = _ids_table(ids)
    linked = (
        select(1)
        .where(pc.evidence_id == evidence_id, pc.criterion_id == u.c.c, pc.deleted_at.is_(None))
        .exists()
    )
    await conn.execute(
        insert(pc).from_select(
            ["evidence_id", "criterion_id"],
            select(literal(evidence_id, pc.evidence_id.type), u.c.c).select_from(u).where(~linked),
        )
    )


async def create_planned_evidence(
    conn: AsyncConnection, experience_id: UUID, inp: dict[str, Any], by: str = BY_TEACHER
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

    evidence_id = await scalar(
        conn,
        insert(PlannedEvidence)
        .values(
            experience_id=h.id,
            name=name,
            kind=inp["kind"],
            value_scale=value_scale,
            max_score=max_score,
            proposed_by=by,
            accepted_at=_accepted_if_teacher(by),
        )
        .returning(PlannedEvidence.id),
    )
    await set_evidence_criteria(conn, evidence_id, criterion_ids)
    if entry_id is not None:
        await place_evidence(conn, evidence_id, entry_id)
    if by == BY_TEACHER:
        await sync_experience(conn, experience_id)
    return evidence_id


async def propose_evidence(conn: AsyncConnection, experience_id: UUID, inp: dict[str, Any]) -> UUID:
    return await create_planned_evidence(conn, experience_id, inp, BY_MAWTA)
