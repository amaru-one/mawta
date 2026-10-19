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
from uuid import UUID

from psycopg import AsyncConnection

from db import fetch_all, fetch_one, fetch_required
from errors import AppError
from repo.classctx import load_class_context

# classDatesSQL: the class dates of %(class)s between %(from)s and %(to)s.
CLASS_DATES_SQL = """
    select distinct cs.session_date
      from class_sessions cs
     where cs.class_id = %(class)s
       and cs.deleted_at is null
       and cs.status <> 'cancelled'
       and cs.session_date between %(from)s and %(to)s
       and not exists (
         select 1 from non_teaching_days n
          where n.tenant_id = cs.tenant_id
            and n.academic_year_id = cs.academic_year_id
            and n.day = cs.session_date
            and n.deleted_at is null
       )"""


def iso(d: date) -> str:
    return d.isoformat()


async def class_dates(conn: AsyncConnection, class_id: UUID, from_: date, to: date) -> list[str]:
    """The class dates of a class in [from, to], in order, as YYYY-MM-DD."""
    rows = await fetch_all(
        conn,
        f"select to_char(d.session_date, 'YYYY-MM-DD') as d from ({CLASS_DATES_SQL}) d"
        " order by d.session_date",
        {"class": class_id, "from": from_, "to": to},
    )
    return [r["d"] for r in rows]


async def count_class_dates(conn: AsyncConnection, class_id: UUID, from_: date, to: date) -> int:
    row = await fetch_required(
        conn,
        f"select count(*) as n from ({CLASS_DATES_SQL}) d",
        {"class": class_id, "from": from_, "to": to},
    )
    return row["n"]


async def scheduled_class_days(
    conn: AsyncConnection, class_id: UUID, from_: date, to: date
) -> list[str]:
    """The dates in [from, to] the class meets: the days its weekly schedule covers plus the
    days it has a session. Unlike class_dates it keeps non-teaching days: the timeline shows a
    feriado as one of the class's slots."""
    rows = await fetch_all(
        conn,
        """
        select to_char(d, 'YYYY-MM-DD') as d
          from generate_series(%(from)s::date, %(to)s::date, interval '1 day') d
         where exists (
           select 1 from class_schedules s
            where s.class_id = %(class)s
              and s.deleted_at is null
              and s.weekday = extract(isodow from d)
              and s.effective_from <= d
              and (s.effective_to is null or d < s.effective_to)
         )
            or exists (
           select 1 from class_sessions cs
            where cs.class_id = %(class)s
              and cs.deleted_at is null
              and cs.status <> 'cancelled'
              and cs.session_date = d
         )
         order by d
        """,
        {"class": class_id, "from": from_, "to": to},
    )
    return [r["d"] for r in rows]


# ------------------------------------------------------------------ plan --


@dataclass
class PlanTerm:
    id: UUID
    name: str
    from_: date
    to: date
    status: str
    sequence: int

    def public(self) -> dict:
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
    row = await fetch_one(
        conn,
        """
        select id, name, starts_on, ends_on, status, sequence
          from terms
         where academic_year_id = %(year)s
           and deleted_at is null
           and (stage is null or stage = %(stage)s)
           and (%(term)s::uuid is null or id = %(term)s::uuid)
         order by case when %(today)s::date between starts_on and ends_on then 0
                       when starts_on > %(today)s::date then 1
                       else 2 end,
                  case when starts_on > %(today)s::date then starts_on end,
                  ends_on desc
         limit 1
        """,
        {"year": cc["year_id"], "stage": cc["stage"], "term": term_id, "today": today},
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró el periodo")
    return PlanTerm(
        row["id"], row["name"], row["starts_on"], row["ends_on"], row["status"], row["sequence"]
    )


async def get_plan(conn: AsyncConnection, class_id: UUID, term: PlanTerm) -> dict:
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
) -> dict[UUID, dict]:
    """Per competency, the distinct evidences of the class in the term that observe it: accepted
    planned evidences and hand-added assessments (those synced from a planned evidence are left
    out, so a planned evidence is counted once). With confirmed_only, evidences of a borrador
    experience are left out (the term overview); without it they count, so an experience's own
    summary sees what it is about to save. Returns {competency_id: {count, kinds}}."""
    rows = await fetch_all(
        conn,
        """
        select u.competency_id, count(distinct u.evidence_id) as n,
               array_agg(distinct u.kind order by u.kind) as kinds
          from (
            select pe.id as evidence_id, cr.competency_id, pe.kind
              from planned_evidences pe
              join learning_experiences le on le.id = pe.experience_id and le.deleted_at is null
              join planned_evidence_criteria pec
                on pec.evidence_id = pe.id and pec.deleted_at is null
              join evaluation_criteria cr on cr.id = pec.criterion_id
               and cr.deleted_at is null and cr.accepted_at is not null
             where le.class_id = %(class)s and le.term_id = %(term)s
               and pe.deleted_at is null and pe.accepted_at is not null
               and (not %(confirmed)s::bool or le.status = 'planificada')
            union all
            select a.id, cr.competency_id, a.kind
              from assessments a
              join assessment_criteria ac on ac.assessment_id = a.id and ac.deleted_at is null
              join evaluation_criteria cr on cr.id = ac.criterion_id and cr.deleted_at is null
             where a.class_id = %(class)s and a.term_id = %(term)s
               and a.planned_evidence_id is null and a.student_id is null
               and a.status in ('published', 'closed') and a.deleted_at is null
          ) u
         group by u.competency_id
        """,
        {"class": class_id, "term": term_id, "confirmed": confirmed_only},
    )
    return {r["competency_id"]: {"count": r["n"], "kinds": r["kinds"]} for r in rows}


async def _fill_evidence_tallies(
    conn: AsyncConnection, class_id: UUID, term_id: UUID, comps: list[dict]
) -> None:
    tally = await term_evidence_by_competency(conn, class_id, term_id, True)
    rows = await fetch_all(
        conn,
        """
        select distinct ec.competency_id
          from experience_competencies ec
          join learning_experiences le on le.id = ec.experience_id
         where le.class_id = %s and le.term_id = %s
           and le.deleted_at is null and ec.deleted_at is null
           and le.status = 'planificada'
        """,
        (class_id, term_id),
    )
    in_term = {r["competency_id"] for r in rows}
    for comp in comps:
        t = tally.get(comp["id"], {"count": 0, "kinds": None})
        comp["evidences_this_term"] = t["count"]
        comp["evidence_kinds"] = t["kinds"] or []
        comp["in_term"] = comp["id"] in in_term


async def free_windows(conn: AsyncConnection, class_id: UUID, term: PlanTerm) -> list[dict]:
    """The stretches of the term not covered by any non-deleted experience of the class (drafts
    included, as learning_experiences_no_overlap counts them), in order, each with how many class
    dates it holds. The planning agent picks experience dates inside one."""
    busy = await fetch_all(
        conn,
        """
        select starts_on, ends_on from learning_experiences
         where class_id = %(class)s and deleted_at is null
           and daterange(starts_on, ends_on, '[]') && daterange(%(from)s::date, %(to)s::date, '[]')
         order by starts_on
        """,
        {"class": class_id, "from": term.from_, "to": term.to},
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
    out = []
    for start, end in gaps:
        n = await count_class_dates(conn, class_id, start, end)
        out.append({"starts_on": iso(start), "ends_on": iso(end), "class_dates": n})
    return out


async def non_teaching_ranges(
    conn: AsyncConnection, year_id: UUID, from_: date, to: date
) -> list[dict]:
    """Group the non-teaching days in [from, to] into runs of consecutive days with the same kind
    and label (gaps and islands: day minus its row number is constant inside a run)."""
    rows = await fetch_all(
        conn,
        """
        select to_char(min(day), 'YYYY-MM-DD') as "from", to_char(max(day), 'YYYY-MM-DD') as "to",
               kind, label
          from (
            select day, kind, label,
                   day - (row_number() over (partition by kind, coalesce(label, '')
                                              order by day))::int as grp
              from non_teaching_days
             where academic_year_id = %(year)s and deleted_at is null
               and day between %(from)s and %(to)s
          ) s
         group by kind, label, grp
         order by min(day)
        """,
        {"year": year_id, "from": from_, "to": to},
    )
    return [
        {"from": r["from"], "to": r["to"], "kind": r["kind"], "label": r["label"]} for r in rows
    ]


async def _plan_experiences(conn: AsyncConnection, class_id: UUID, term_id: UUID) -> list[dict]:
    rows = await fetch_all(
        conn,
        """
        select le.id, le.title, le.status, le.starts_on, le.ends_on,
               (select count(*) from evaluation_criteria cr
                 where cr.experience_id = le.id and cr.deleted_at is null
                   and cr.accepted_at is null)
             + (select count(*) from planned_evidences pe
                 where pe.experience_id = le.id and pe.deleted_at is null
                   and pe.accepted_at is null)
             + (select count(*) from session_outline_entries se
                 where se.experience_id = le.id and se.deleted_at is null
                   and se.accepted_at is null) as pending_proposals
          from learning_experiences le
         where le.class_id = %s and le.term_id = %s and le.deleted_at is null
         order by le.starts_on
        """,
        (class_id, term_id),
    )
    out = []
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


async def experience_coverage(conn: AsyncConnection, experience_id: UUID) -> list[dict]:
    """An experience's competencies with how many of their capabilities an accepted criterion of
    the experience looks at."""
    rows = await fetch_all(
        conn,
        """
        select c.id, c.code, c.name,
               (select count(*) from capabilities cap
                 where cap.competency_id = c.id and cap.is_active
                   and cap.deleted_at is null) as capabilities_total,
               (select count(distinct x.capability_id)
                  from evaluation_criteria cr
                  join evaluation_criterion_capabilities x
                    on x.criterion_id = cr.id and x.deleted_at is null
                 where cr.experience_id = ec.experience_id and cr.competency_id = c.id
                   and cr.deleted_at is null and cr.accepted_at is not null)
                 as capabilities_with_criteria
          from experience_competencies ec
          join competencies c on c.id = ec.competency_id
         where ec.experience_id = %s and ec.deleted_at is null
         order by c.sort_order, c.code
        """,
        (experience_id,),
    )
    return rows


async def _plan_competencies(
    conn: AsyncConnection, class_id: UUID, cc: dict, term: PlanTerm
) -> list[dict]:
    """The contract's tracking rule for every competency of the class's área:

    - planificada: a confirmed (status planificada) experience of this class in this term works it;
    - toca: otherwise, when it still needs terms to reach two worked terms in the year and the
      terms left (this one included) are no more than it needs;
    - puede_esperar: otherwise.

    A worked term is a term of the year with a confirmed experience of this class working the
    competency. A borrador is still being built, so it does not count as work done."""
    rows = await fetch_all(
        conn,
        """
        with worked as (
          select ec.competency_id,
                 array_agg(distinct t.sequence::int order by t.sequence::int) as seqs,
                 bool_or(le.term_id = %(term)s) as this_term
            from learning_experiences le
            join experience_competencies ec on ec.experience_id = le.id and ec.deleted_at is null
            join terms t on t.id = le.term_id
           where le.class_id = %(class)s and le.academic_year_id = %(year)s
             and le.deleted_at is null and le.status = 'planificada'
           group by ec.competency_id
        ),
        terms_left as (
          select count(*)::int as n
            from terms
           where academic_year_id = %(year)s and deleted_at is null
             and (stage is null or stage = %(stage)s)
             and sequence >= %(seq)s
        ),
        covered as (
          select cr.competency_id, count(distinct x.capability_id)::int as n
            from learning_experiences le
            join evaluation_criteria cr on cr.experience_id = le.id
                 and cr.deleted_at is null and cr.accepted_at is not null
            join evaluation_criterion_capabilities x
              on x.criterion_id = cr.id and x.deleted_at is null
           where le.class_id = %(class)s and le.term_id = %(term)s and le.deleted_at is null
             and le.status = 'planificada'
           group by cr.competency_id
        )
        select c.id, c.code, c.name,
               case
                 when coalesce(w.this_term, false) then 'planificada'
                 when greatest(0, 2 - coalesce(cardinality(w.seqs), 0)) > 0
                  and (select n from terms_left) <= greatest(0, 2 - coalesce(cardinality(w.seqs), 0))
                   then 'toca'
                 else 'puede_esperar'
               end as status,
               coalesce(w.seqs, '{}') as terms_worked,
               (select count(*)::int from capabilities cap
                 where cap.competency_id = c.id and cap.is_active
                   and cap.deleted_at is null) as capabilities_total,
               coalesce(cv.n, 0) as capabilities_covered_this_term
          from competencies c
          left join worked w on w.competency_id = c.id
          left join covered cv on cv.competency_id = c.id
         where c.subject_id = %(subject)s and c.is_active and c.deleted_at is null
         order by c.sort_order, c.code
        """,
        {
            "class": class_id,
            "subject": cc["subject_id"],
            "term": term.id,
            "year": cc["year_id"],
            "stage": cc["stage"],
            "seq": term.sequence,
        },
    )
    return rows


# ------------------------------------------------------------ curriculum --


async def get_curriculum(conn: AsyncConnection, class_id: UUID) -> dict:
    """The competencies of the class's área with their capabilities, the standard of the class's
    cycle and the performances of the class's grade. The standard is the main source of criteria;
    performances are optional support."""
    cc = await load_class_context(conn, class_id)
    grade = {"code": cc["grade_code"], "cycle": cc["cycle"], "expected_level": None}
    if cc["cycle"] is not None:
        mapping = await fetch_one(
            conn,
            """
            select expected_level from standard_level_mappings
             where modality = 'ebr' and cycle = %s and deleted_at is null
            """,
            (cc["cycle"],),
        )
        if mapping is not None:
            grade["expected_level"] = mapping["expected_level"]

    comps = await fetch_all(
        conn,
        """
        select id, code, name, kind from competencies
         where subject_id = %s and is_active and deleted_at is null
         order by sort_order, code
        """,
        (cc["subject_id"],),
    )
    by_id: dict[UUID, dict] = {}
    for c in comps:
        c.update(standard=None, capabilities=[], performances=[])
        by_id[c["id"]] = c

    if grade["expected_level"] is not None:
        for r in await fetch_all(
            conn,
            """
            select s.competency_id, s.level, s.official_text
              from learning_standards s
              join competencies c on c.id = s.competency_id
             where c.subject_id = %s and s.level = %s and s.deleted_at is null
            """,
            (cc["subject_id"], grade["expected_level"]),
        ):
            if r["competency_id"] in by_id:
                by_id[r["competency_id"]]["standard"] = {
                    "level": r["level"],
                    "text": r["official_text"],
                }

    for r in await fetch_all(
        conn,
        """
        select cap.competency_id, cap.id, cap.code, cap.name
          from capabilities cap
          join competencies c on c.id = cap.competency_id
         where c.subject_id = %s and cap.is_active and cap.deleted_at is null
         order by cap.sort_order, cap.code
        """,
        (cc["subject_id"],),
    ):
        if r["competency_id"] in by_id:
            by_id[r["competency_id"]]["capabilities"].append(
                {"id": r["id"], "code": r["code"], "name": r["name"]}
            )

    for r in await fetch_all(
        conn,
        """
        select p.competency_id, p.id, p.sort_order, p.official_text, p.en_proceso,
               p.suggested_capability_id
          from grade_level_performances p
          join competencies c on c.id = p.competency_id
         where c.subject_id = %s and p.grade_level_id = %s and p.deleted_at is null
         order by p.sort_order
        """,
        (cc["subject_id"], cc["grade_level_id"]),
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


async def get_calendar(conn: AsyncConnection, class_id: UUID, from_: date, to: date) -> dict:
    """The class dates and the non-teaching days in [from, to]. The range may be at most as long
    as the longest term of the class's year."""
    cc = await load_class_context(conn, class_id)
    if to < from_:
        raise AppError(400, "bad_request", "to no puede ser anterior a from")
    row = await fetch_required(
        conn,
        """
        select max(ends_on - starts_on + 1) as max_days from terms
         where academic_year_id = %s and deleted_at is null
        """,
        (cc["year_id"],),
    )
    days = (to - from_).days + 1
    if row["max_days"] is None or days > row["max_days"]:
        raise AppError(400, "bad_request", "el rango puede abarcar como máximo un periodo")

    dates = await class_dates(conn, class_id, from_, to)
    rows = await fetch_all(
        conn,
        """
        select to_char(day, 'YYYY-MM-DD') as date, kind, label from non_teaching_days
         where academic_year_id = %s and deleted_at is null and day between %s and %s
         order by day
        """,
        (cc["year_id"], from_, to),
    )
    return {"class_dates": dates, "non_teaching_days": rows}
