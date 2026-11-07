"""Term planning, read side: "Tu trimestre", curriculum and calendar.

A teacher plans one class's term as learning experiences, each with competencies, criteria,
planned evidences and a light session outline. Two rules hold across the planning modules:

- A class date is a date with a non-cancelled class_sessions row of the class that is not a
  non_teaching_days day. A double block is one date.
- Something Mawta proposed only counts once the teacher accepted or edited it: coverage and
  "capability without criterion" look at accepted_at, so a pending proposal never reads as
  planned work.

Only the class's área competencies take part. The schema has no way to assign a transversal
competency to a class.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Date,
    Integer,
    and_,
    case,
    cast,
    distinct,
    extract,
    false,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_all, fetch_one, scalar
from errors import AppError
from mawta_schema.tables import (
    Assessment,
    AssessmentCriterion,
    Capability,
    ClassSchedule,
    ClassSession,
    Competency,
    EvaluationCriterion,
    EvaluationCriterionCapability,
    ExperienceCompetency,
    GradeLevelPerformance,
    LearningExperience,
    LearningStandard,
    NonTeachingDay,
    PlannedEvidence,
    PlannedEvidenceCriterion,
    SessionOutlineEntry,
    StandardLevelMapping,
    Term,
)
from repo.classctx import load_class_context


def _class_dates(class_id: UUID, from_: date, to: date):
    """The class dates of a class between from_ and to, as a subquery with session_date."""
    cs, n = ClassSession, NonTeachingDay
    holiday = (
        select(1)
        .where(
            n.academic_year_id == cs.academic_year_id,
            n.day == cs.session_date,
            n.deleted_at.is_(None),
        )
        .exists()
    )
    return (
        select(cs.session_date)
        .distinct()
        .where(
            cs.class_id == class_id,
            cs.deleted_at.is_(None),
            cs.status != "cancelled",
            cs.session_date.between(from_, to),
            ~holiday,
        )
        .subquery("d")
    )


def iso(d: date) -> str:
    return d.isoformat()


async def class_dates(conn: AsyncConnection, class_id: UUID, from_: date, to: date) -> list[str]:
    """The class dates of a class in [from, to], in order, as YYYY-MM-DD."""
    d = _class_dates(class_id, from_, to)
    result = await conn.execute(
        select(func.to_char(d.c.session_date, "YYYY-MM-DD")).order_by(d.c.session_date)
    )
    return list(result.scalars())


async def count_class_dates(conn: AsyncConnection, class_id: UUID, from_: date, to: date) -> int:
    return await scalar(conn, select(func.count()).select_from(_class_dates(class_id, from_, to)))


async def scheduled_class_days(
    conn: AsyncConnection, class_id: UUID, from_: date, to: date
) -> list[str]:
    """The dates in [from, to] the class meets: the days its weekly schedule covers plus the
    days it has a session. Unlike class_dates it keeps non-teaching days: the timeline shows a
    feriado as one of the class's slots."""
    d = func.generate_series(
        literal(from_, Date), literal(to, Date), timedelta(days=1)
    ).column_valued("d")
    s, cs = ClassSchedule, ClassSession
    scheduled = (
        select(1)
        .where(
            s.class_id == class_id,
            s.deleted_at.is_(None),
            s.weekday == extract("isodow", d),
            s.effective_from <= d,
            or_(s.effective_to.is_(None), d < s.effective_to),
        )
        .exists()
    )
    has_session = (
        select(1)
        .where(
            cs.class_id == class_id,
            cs.deleted_at.is_(None),
            cs.status != "cancelled",
            cs.session_date == d,
        )
        .exists()
    )
    result = await conn.execute(
        select(func.to_char(d, "YYYY-MM-DD")).where(or_(scheduled, has_session)).order_by(d)
    )
    return list(result.scalars())


# ------------------------------------------------------------------ plan --


@dataclass
class PlanTerm:
    id: UUID
    name: str
    from_: date
    to: date
    status: str
    sequence: int

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "starts_on": iso(self.from_),
            "ends_on": iso(self.to),
            "status": self.status,
        }

    def range(self) -> tuple[date, date]:
        return self.from_, self.to


async def resolve_plan_term(
    conn: AsyncConnection, class_id: UUID, term_id: UUID | None, today: date
) -> PlanTerm:
    """The term "Tu trimestre" shows: term_id when given (it must be a term of the class's year),
    else the term containing today, else the next one, else the last one. Terms of another stage
    are skipped. Not resolve_term: planning shows where the teacher is in the year, by date,
    whether or not the term has been activated yet."""
    cc = await load_class_context(conn, class_id)
    only = [] if term_id is None else [Term.id == term_id]
    row = await fetch_one(
        conn,
        select(Term.id, Term.name, Term.starts_on, Term.ends_on, Term.status, Term.sequence)
        .where(
            Term.academic_year_id == cc["year_id"],
            Term.deleted_at.is_(None),
            or_(Term.stage.is_(None), Term.stage == cc["stage"]),
            *only,
        )
        .order_by(
            case(
                (literal(today, Date).between(Term.starts_on, Term.ends_on), 0),
                (Term.starts_on > today, 1),
                else_=2,
            ),
            case((Term.starts_on > today, Term.starts_on)),
            Term.ends_on.desc(),
        )
        .limit(1),
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró el periodo")
    return PlanTerm(
        row["id"], row["name"], row["starts_on"], row["ends_on"], row["status"], row["sequence"]
    )


async def get_plan(conn: AsyncConnection, class_id: UUID, term: PlanTerm) -> dict[str, Any]:
    """Build "Tu trimestre" for one class and term."""
    cc = await load_class_context(conn, class_id)
    non_teaching = await non_teaching_ranges(conn, cc["year_id"], term.from_, term.to)
    total = await count_class_dates(conn, class_id, term.from_, term.to)
    scheduled = await scheduled_class_days(conn, class_id, term.from_, term.to)
    experiences = await _plan_experiences(conn, class_id, term.id)
    competencies = await _plan_competencies(conn, class_id, cc, term)
    await _fill_evidence_tallies(conn, class_id, term.id, competencies)
    return {
        "term": term.public(),
        "non_teaching_days": non_teaching,
        "class_dates_total": total,
        # The days the weekly schedule meets in the term, holidays included: a feriado on a
        # class day is a class slot the timeline marks, not a missing one.
        "scheduled_class_days": scheduled,
        "experiences": experiences,
        "competencies": competencies,
    }


async def term_evidence_by_competency(
    conn: AsyncConnection, class_id: UUID, term_id: UUID, confirmed_only: bool
) -> dict[UUID, dict[str, Any]]:
    """Per competency, the distinct evidences of the class in the term that observe it: accepted
    planned evidences and hand-added assessments (those synced from a planned evidence are left
    out, so a planned evidence is counted once). With confirmed_only, evidences of a borrador
    experience are left out (the term overview); without it they count, so an experience's own
    summary sees what it is about to save. Returns {competency_id: {count, kinds}}."""
    pe, le, pec, cr = (
        PlannedEvidence,
        LearningExperience,
        PlannedEvidenceCriterion,
        EvaluationCriterion,
    )
    confirmed = [le.status == "planificada"] if confirmed_only else []
    planned = (
        select(pe.id.label("evidence_id"), cr.competency_id, pe.kind)
        .join(le, (le.id == pe.experience_id) & le.deleted_at.is_(None))
        .join(pec, (pec.evidence_id == pe.id) & pec.deleted_at.is_(None))
        .join(
            cr,
            (cr.id == pec.criterion_id) & cr.deleted_at.is_(None) & cr.accepted_at.is_not(None),
        )
        .where(
            le.class_id == class_id,
            le.term_id == term_id,
            pe.deleted_at.is_(None),
            pe.accepted_at.is_not(None),
            *confirmed,
        )
    )
    a, ac = Assessment, AssessmentCriterion
    by_hand = (
        select(a.id, cr.competency_id, a.kind)
        .join(ac, (ac.assessment_id == a.id) & ac.deleted_at.is_(None))
        .join(cr, (cr.id == ac.criterion_id) & cr.deleted_at.is_(None))
        .where(
            a.class_id == class_id,
            a.term_id == term_id,
            a.planned_evidence_id.is_(None),
            a.student_id.is_(None),
            a.status.in_(("published", "closed")),
            a.deleted_at.is_(None),
        )
    )
    u = union_all(planned, by_hand).subquery("u")
    rows = await fetch_all(
        conn,
        select(
            u.c.competency_id,
            func.count(distinct(u.c.evidence_id)).label("n"),
            func.array_agg(aggregate_order_by(distinct(u.c.kind), u.c.kind)).label("kinds"),
        ).group_by(u.c.competency_id),
    )
    return {r["competency_id"]: {"count": r["n"], "kinds": r["kinds"]} for r in rows}


async def _fill_evidence_tallies(
    conn: AsyncConnection, class_id: UUID, term_id: UUID, comps: list[dict[str, Any]]
) -> None:
    tally = await term_evidence_by_competency(conn, class_id, term_id, True)
    ec, le = ExperienceCompetency, LearningExperience
    result = await conn.execute(
        select(ec.competency_id)
        .distinct()
        .join(le, le.id == ec.experience_id)
        .where(
            le.class_id == class_id,
            le.term_id == term_id,
            le.deleted_at.is_(None),
            ec.deleted_at.is_(None),
            le.status == "planificada",
        )
    )
    in_term = set(result.scalars())
    for comp in comps:
        t = tally.get(comp["id"], {"count": 0, "kinds": None})
        comp["evidences_this_term"] = t["count"]
        comp["evidence_kinds"] = t["kinds"] or []
        comp["in_term"] = comp["id"] in in_term


async def free_windows(
    conn: AsyncConnection, class_id: UUID, term: PlanTerm
) -> list[dict[str, Any]]:
    """The stretches of the term not covered by any non-deleted experience of the class (drafts
    included, as learning_experiences_no_overlap counts them), in order, each with how many class
    dates it holds. The planning agent picks experience dates inside one."""
    le = LearningExperience
    busy = await fetch_all(
        conn,
        select(le.starts_on, le.ends_on)
        .where(
            le.class_id == class_id,
            le.deleted_at.is_(None),
            func.daterange(le.starts_on, le.ends_on, "[]").op("&&")(
                func.daterange(term.from_, term.to, "[]")
            ),
        )
        .order_by(le.starts_on),
    )
    gaps: list[tuple[date, date]] = []
    cursor = term.from_
    one = timedelta(days=1)
    for b in busy:
        if b["starts_on"] > cursor:
            gaps.append((cursor, b["starts_on"] - one))
        nxt = b["ends_on"] + one
        if nxt > cursor:
            cursor = nxt
    if cursor <= term.to:
        gaps.append((cursor, term.to))
    out: list[dict[str, Any]] = []
    for start, end in gaps:
        n = await count_class_dates(conn, class_id, start, end)
        out.append({"starts_on": iso(start), "ends_on": iso(end), "class_dates": n})
    return out


async def non_teaching_ranges(
    conn: AsyncConnection, year_id: UUID, from_: date, to: date
) -> list[dict[str, Any]]:
    """Group the non-teaching days in [from, to] into runs of consecutive days with the same kind
    and label (gaps and islands: day minus its row number is constant inside a run)."""
    n = NonTeachingDay
    position = func.row_number().over(
        partition_by=(n.kind, func.coalesce(n.label, "")), order_by=n.day
    )
    s = (
        select(n.day, n.kind, n.label, (n.day - cast(position, Integer)).label("grp"))
        .where(n.academic_year_id == year_id, n.deleted_at.is_(None), n.day.between(from_, to))
        .subquery("s")
    )
    rows = await fetch_all(
        conn,
        select(
            func.to_char(func.min(s.c.day), "YYYY-MM-DD").label("from"),
            func.to_char(func.max(s.c.day), "YYYY-MM-DD").label("to"),
            s.c.kind,
            s.c.label,
        )
        .group_by(s.c.kind, s.c.label, s.c.grp)
        .order_by(func.min(s.c.day)),
    )
    return [
        {"from": r["from"], "to": r["to"], "kind": r["kind"], "label": r["label"]} for r in rows
    ]


def _unaccepted(model: Any, experience_id: Any) -> Any:
    return (
        select(func.count())
        .where(
            model.experience_id == experience_id,
            model.deleted_at.is_(None),
            model.accepted_at.is_(None),
        )
        .scalar_subquery()
    )


async def _plan_experiences(
    conn: AsyncConnection, class_id: UUID, term_id: UUID
) -> list[dict[str, Any]]:
    le = LearningExperience
    pending = (
        _unaccepted(EvaluationCriterion, le.id)
        + _unaccepted(PlannedEvidence, le.id)
        + _unaccepted(SessionOutlineEntry, le.id)
    )
    rows = await fetch_all(
        conn,
        select(
            le.id,
            le.title,
            le.status,
            le.starts_on,
            le.ends_on,
            pending.label("pending_proposals"),
        )
        .where(le.class_id == class_id, le.term_id == term_id, le.deleted_at.is_(None))
        .order_by(le.starts_on),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "title": r["title"],
                "status": r["status"],
                "starts_on": iso(r["starts_on"]),
                "ends_on": iso(r["ends_on"]),
                "class_dates": await count_class_dates(
                    conn, class_id, r["starts_on"], r["ends_on"]
                ),
                "competencies": await experience_coverage(conn, r["id"]),
                "pending_proposals": r["pending_proposals"],
            }
        )
    return out


def _active_capabilities(competency_id: Any) -> Any:
    return (
        select(cast(func.count(), Integer))
        .where(
            Capability.competency_id == competency_id,
            Capability.is_active,
            Capability.deleted_at.is_(None),
        )
        .scalar_subquery()
    )


async def experience_coverage(conn: AsyncConnection, experience_id: UUID) -> list[dict[str, Any]]:
    """An experience's competencies with how many of their capabilities an accepted criterion of
    the experience looks at."""
    ec, cr, x = ExperienceCompetency, EvaluationCriterion, EvaluationCriterionCapability
    with_criteria = (
        select(func.count(distinct(x.capability_id)))
        .select_from(cr)
        .join(x, (x.criterion_id == cr.id) & x.deleted_at.is_(None))
        .where(
            cr.experience_id == ec.experience_id,
            cr.competency_id == Competency.id,
            cr.deleted_at.is_(None),
            cr.accepted_at.is_not(None),
        )
        .scalar_subquery()
    )
    total = (
        select(func.count())
        .where(
            Capability.competency_id == Competency.id,
            Capability.is_active,
            Capability.deleted_at.is_(None),
        )
        .scalar_subquery()
    )
    rows = await fetch_all(
        conn,
        select(
            Competency.id,
            Competency.code,
            Competency.name,
            total.label("capabilities_total"),
            with_criteria.label("capabilities_with_criteria"),
        )
        .select_from(ec)
        .join(Competency, Competency.id == ec.competency_id)
        .where(ec.experience_id == experience_id, ec.deleted_at.is_(None))
        .order_by(Competency.sort_order, Competency.code),
    )
    return [dict(r) for r in rows]


async def _plan_competencies(
    conn: AsyncConnection, class_id: UUID, cc: dict[str, Any], term: PlanTerm
) -> list[dict[str, Any]]:
    """The contract's tracking rule for every competency of the class's área:

    - planificada: a confirmed (status planificada) experience of this class in this term works it;
    - toca: otherwise, when it still needs terms to reach two worked terms in the year and the
      terms left (this one included) are no more than it needs;
    - puede_esperar: otherwise.

    A worked term is a term of the year with a confirmed experience of this class working the
    competency. A borrador is still being built, so it does not count as work done."""
    le, ec, cr, x = (
        LearningExperience,
        ExperienceCompetency,
        EvaluationCriterion,
        EvaluationCriterionCapability,
    )
    seq = cast(Term.sequence, Integer)
    worked = (
        select(
            ec.competency_id,
            func.array_agg(aggregate_order_by(distinct(seq), seq)).label("seqs"),
            func.bool_or(le.term_id == term.id).label("this_term"),
        )
        .select_from(le)
        .join(ec, (ec.experience_id == le.id) & ec.deleted_at.is_(None))
        .join(Term, Term.id == le.term_id)
        .where(
            le.class_id == class_id,
            le.academic_year_id == cc["year_id"],
            le.deleted_at.is_(None),
            le.status == "planificada",
        )
        .group_by(ec.competency_id)
        .cte("worked")
    )
    terms_left = (
        select(cast(func.count(), Integer))
        .where(
            Term.academic_year_id == cc["year_id"],
            Term.deleted_at.is_(None),
            or_(Term.stage.is_(None), Term.stage == cc["stage"]),
            Term.sequence >= term.sequence,
        )
        .scalar_subquery()
    )
    covered = (
        select(cr.competency_id, cast(func.count(distinct(x.capability_id)), Integer).label("n"))
        .select_from(le)
        .join(
            cr,
            (cr.experience_id == le.id) & cr.deleted_at.is_(None) & cr.accepted_at.is_not(None),
        )
        .join(x, (x.criterion_id == cr.id) & x.deleted_at.is_(None))
        .where(
            le.class_id == class_id,
            le.term_id == term.id,
            le.deleted_at.is_(None),
            le.status == "planificada",
        )
        .group_by(cr.competency_id)
        .cte("covered")
    )
    need = func.greatest(0, 2 - func.coalesce(func.cardinality(worked.c.seqs), 0))
    rows = await fetch_all(
        conn,
        select(
            Competency.id,
            Competency.code,
            Competency.name,
            case(
                (func.coalesce(worked.c.this_term, false()), "planificada"),
                (and_(need > 0, terms_left <= need), "toca"),
                else_="puede_esperar",
            ).label("status"),
            func.coalesce(worked.c.seqs, literal([], ARRAY(Integer))).label("terms_worked"),
            _active_capabilities(Competency.id).label("capabilities_total"),
            func.coalesce(covered.c.n, 0).label("capabilities_covered_this_term"),
        )
        .outerjoin(worked, worked.c.competency_id == Competency.id)
        .outerjoin(covered, covered.c.competency_id == Competency.id)
        .where(
            Competency.subject_id == cc["subject_id"],
            Competency.is_active,
            Competency.deleted_at.is_(None),
        )
        .order_by(Competency.sort_order, Competency.code),
    )
    return [dict(r) for r in rows]


# ------------------------------------------------------------ curriculum --


async def get_curriculum(conn: AsyncConnection, class_id: UUID) -> dict[str, Any]:
    """The competencies of the class's área with their capabilities, the standard of the class's
    cycle and the performances of the class's grade. The standard is the main source of criteria;
    performances are optional support."""
    cc = await load_class_context(conn, class_id)
    grade = {"code": cc["grade_code"], "cycle": cc["cycle"], "expected_level": None}
    if cc["cycle"] is not None:
        m = StandardLevelMapping
        mapping = await fetch_one(
            conn,
            select(m.expected_level).where(
                m.modality == "ebr", m.cycle == cc["cycle"], m.deleted_at.is_(None)
            ),
        )
        if mapping is not None:
            grade["expected_level"] = mapping["expected_level"]

    comps = await fetch_all(
        conn,
        select(Competency.id, Competency.code, Competency.name, Competency.kind)
        .where(
            Competency.subject_id == cc["subject_id"],
            Competency.is_active,
            Competency.deleted_at.is_(None),
        )
        .order_by(Competency.sort_order, Competency.code),
    )
    by_id: dict[UUID, dict[str, Any]] = {}
    for row in comps:
        c = dict(row)
        c.update(standard=None, capabilities=[], performances=[])
        by_id[c["id"]] = c

    in_subject = Competency.subject_id == cc["subject_id"]
    if grade["expected_level"] is not None:
        s = LearningStandard
        for r in await fetch_all(
            conn,
            select(s.competency_id, s.level, s.official_text)
            .join(Competency, Competency.id == s.competency_id)
            .where(in_subject, s.level == grade["expected_level"], s.deleted_at.is_(None)),
        ):
            if r["competency_id"] in by_id:
                by_id[r["competency_id"]]["standard"] = {
                    "level": r["level"],
                    "text": r["official_text"],
                }

    cap = Capability
    for r in await fetch_all(
        conn,
        select(cap.competency_id, cap.id, cap.code, cap.name)
        .join(Competency, Competency.id == cap.competency_id)
        .where(in_subject, cap.is_active, cap.deleted_at.is_(None))
        .order_by(cap.sort_order, cap.code),
    ):
        if r["competency_id"] in by_id:
            by_id[r["competency_id"]]["capabilities"].append(
                {"id": r["id"], "code": r["code"], "name": r["name"]}
            )

    p = GradeLevelPerformance
    for r in await fetch_all(
        conn,
        select(
            p.competency_id,
            p.id,
            p.sort_order,
            p.official_text,
            p.en_proceso,
            p.suggested_capability_id,
        )
        .join(Competency, Competency.id == p.competency_id)
        .where(in_subject, p.grade_level_id == cc["grade_level_id"], p.deleted_at.is_(None))
        .order_by(p.sort_order),
    ):
        if r["competency_id"] in by_id:
            by_id[r["competency_id"]]["performances"].append(
                {
                    "id": r["id"],
                    "order": r["sort_order"],
                    "text": r["official_text"],
                    "en_proceso": r["en_proceso"],
                    "suggested_capability_id": r["suggested_capability_id"],
                }
            )
    return {"grade": grade, "competencies": list(by_id.values())}


# -------------------------------------------------------------- calendar --


async def get_calendar(
    conn: AsyncConnection, class_id: UUID, from_: date, to: date
) -> dict[str, Any]:
    """The class dates and the non-teaching days in [from, to]. The range may be at most as long
    as the longest term of the class's year."""
    cc = await load_class_context(conn, class_id)
    if to < from_:
        raise AppError(400, "bad_request", "to no puede ser anterior a from")
    max_days = await scalar(
        conn,
        select(func.max(Term.ends_on - Term.starts_on + 1)).where(
            Term.academic_year_id == cc["year_id"], Term.deleted_at.is_(None)
        ),
    )
    days = (to - from_).days + 1
    if max_days is None or days > max_days:
        raise AppError(400, "bad_request", "el rango puede abarcar como máximo un periodo")

    dates = await class_dates(conn, class_id, from_, to)
    n = NonTeachingDay
    rows = await fetch_all(
        conn,
        select(func.to_char(n.day, "YYYY-MM-DD").label("date"), n.kind, n.label)
        .where(
            n.academic_year_id == cc["year_id"], n.deleted_at.is_(None), n.day.between(from_, to)
        )
        .order_by(n.day),
    )
    return {"class_dates": dates, "non_teaching_days": [dict(r) for r in rows]}
