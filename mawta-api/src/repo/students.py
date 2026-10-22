"""The class list and one student's evidence."""

from datetime import date
from typing import Any, SupportsFloat
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from db import fetch_all


async def list_class_students(
    conn: AsyncConnection[DictRow],
    class_id: UUID,
    competency_id: UUID | None,
    term_id: UUID,
    as_of: date,
) -> list[dict[str, Any]]:
    """The class roster as of today with each student's level in one competencia.

    Without competency_id the list is just the roster: no level, and the evidence count
    covers the whole área. level is None when the teacher has not asserted one this period:
    a real state under RVM 048-2024 5.1.2.2, never rendered as C or zero.
    """
    rows = await fetch_all(
        conn,
        """
        select st.id as student_id,
               st.paternal_surname
                 || coalesce(' ' || st.maternal_surname, '')
                 || ', ' || coalesce(st.preferred_name, st.given_name) as full_name,
               l.code as level,
               (select count(*)
                  from assessments a
                 where a.class_id = %(class)s and a.term_id = %(term)s
                   and a.status = 'published' and a.deleted_at is null
                   and (a.student_id is null or a.student_id = st.id)
                   and (%(comp)s::uuid is null or exists (
                         select 1
                           from assessment_criteria ac
                           join evaluation_criteria ec on ec.id = ac.criterion_id
                          where ac.assessment_id = a.id and ac.deleted_at is null
                            and ec.competency_id = %(comp)s::uuid))
               ) as evidence_count
          from section_memberships sm
          join classes c on c.section_id = sm.section_id and c.id = %(class)s
          join students st on st.id = sm.student_id and st.deleted_at is null
          left join competency_term_levels ctl
                 on ctl.student_id = st.id
                and ctl.competency_id = %(comp)s::uuid
                and ctl.term_id = %(term)s
                and ctl.superseded_at is null and ctl.deleted_at is null
          left join grade_scale_levels l on l.id = ctl.scale_level_id
         where sm.joined_on <= %(d)s and (sm.left_on is null or sm.left_on > %(d)s)
           and sm.deleted_at is null and c.deleted_at is null
         order by st.paternal_surname, st.maternal_surname nulls first, st.given_name
        """,
        {"class": class_id, "comp": competency_id, "term": term_id, "d": as_of},
    )
    return rows


async def list_student_evidence(
    conn: AsyncConnection[DictRow],
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID | None,
    term_id: UUID,
) -> list[dict[str, Any]]:
    """The period's evidencia for one student, narrowed to the competencia being judged
    through assessment_criteria, each piece carrying the student's valuation. Nothing here is
    aggregated: the list is material for a judgement the teacher makes."""
    rows = await fetch_all(
        conn,
        """
        select a.id as assessment_id, a.title, a.kind, a.value_scale, a.max_score, a.due_at,
               a.student_id is not null as is_personal,
               s.id as score_id, s.status, s.raw_value, l.code as level
          from assessments a
          left join scores s on s.assessment_id = a.id and s.student_id = %(student)s
                             and s.superseded_at is null and s.deleted_at is null
          left join grade_scale_levels l on l.id = s.scale_level_id
         where a.class_id = %(class)s and a.term_id = %(term)s
           and a.status = 'published' and a.deleted_at is null
           and (a.student_id is null or a.student_id = %(student)s)
           and (%(comp)s::uuid is null or exists (
                 select 1
                   from assessment_criteria ac
                   join evaluation_criteria ec on ec.id = ac.criterion_id
                  where ac.assessment_id = a.id and ac.deleted_at is null
                    and ec.competency_id = %(comp)s::uuid))
         order by a.due_at nulls last, a.title
        """,
        {"class": class_id, "student": student_id, "term": term_id, "comp": competency_id},
    )
    entries: dict[UUID, dict[str, Any]] = {}
    for r in rows:
        score = None
        max_score = _float(r["max_score"])
        if r["score_id"] is not None:
            raw = _float(r["raw_value"])
            pct = raw / max_score * 100 if raw is not None and max_score and max_score > 0 else None
            score = {
                "score_id": r["score_id"],
                "status": r["status"],
                "raw_value": raw,
                "percentage": pct,
                "level": r["level"],
            }
        entries[r["assessment_id"]] = {
            "assessment_id": r["assessment_id"],
            "title": r["title"],
            "kind": r["kind"],
            "value_scale": r["value_scale"],
            "max_score": max_score,
            "due_at": r["due_at"],
            "is_personal": r["is_personal"],
            "criteria": [],
            "score": score,
        }

    # The criterio tags, read separately: one assessment carries several, and joining them
    # above would multiply the rows.
    crit_rows = await fetch_all(
        conn,
        """
        select ac.assessment_id, ec.id as criterion_id, ec.code, ec.description
          from assessment_criteria ac
          join assessments a on a.id = ac.assessment_id
          join evaluation_criteria ec on ec.id = ac.criterion_id
         where a.class_id = %(class)s and a.term_id = %(term)s
           and a.status = 'published' and a.deleted_at is null
           and (a.student_id is null or a.student_id = %(student)s)
           and ac.deleted_at is null and ec.deleted_at is null
         order by ec.sort_order, ec.code
        """,
        {"class": class_id, "term": term_id, "student": student_id},
    )
    for c in crit_rows:
        entry = entries.get(c["assessment_id"])
        if entry is not None:
            entry["criteria"].append(
                {
                    "criterion_id": c["criterion_id"],
                    "code": c["code"],
                    "description": c["description"],
                }
            )
    return list(entries.values())


def _float(value: SupportsFloat | None) -> float | None:
    return float(value) if value is not None else None
