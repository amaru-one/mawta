"""What the descriptive-conclusions agent reads about one student, one competency and one term.
Every query is scoped by the ids the server put on the generation, never by anything the model asked
for."""

from datetime import date
from uuid import UUID

from psycopg import AsyncConnection

from db import fetch_all, fetch_one, fetch_required
from repo.competencies import _conclusion_requirement
from repo.planning import MIN_CONCLUSION_EVIDENCES
from repo.redaction import (
    ATTRIBUTION_DISCARDED,
    ATTRIBUTION_PENDING,
    student_names,
)
from repo.roster import roster_as_of

__all__ = ["MIN_CONCLUSION_EVIDENCES"]


async def conclusion_requirement(
    conn: AsyncConnection, class_id: UUID, student_id: UUID, competency_id: UUID, term_id: UUID
) -> str:
    """Why a conclusion is (or is not) mandatory for this competency, student and period."""
    return await _conclusion_requirement(conn, class_id, student_id, competency_id, term_id)


async def competency_in_class(conn: AsyncConnection, class_id: UUID, competency_id: UUID) -> bool:
    """Whether a competency belongs to the área the class teaches."""
    row = await fetch_required(
        conn,
        """
        select exists (
          select 1 from competencies c
            join courses co on co.subject_id = c.subject_id
            join classes cl on cl.course_id = co.id
           where cl.id = %s and c.id = %s and c.deleted_at is null) as ok
        """,
        (class_id, competency_id),
    )
    return row["ok"]


async def live_competency_level(
    conn: AsyncConnection, student_id: UUID, competency_id: UUID, term_id: UUID
) -> str | None:
    """The level a teacher asserted for this student, competency and term; None when none yet."""
    row = await fetch_one(
        conn,
        """
        select l.code from competency_term_levels ctl
          join grade_scale_levels l on l.id = ctl.scale_level_id
         where ctl.student_id = %s and ctl.competency_id = %s and ctl.term_id = %s
           and ctl.superseded_at is null and ctl.deleted_at is null
        """,
        (student_id, competency_id, term_id),
    )
    return row["code"] if row else None


async def get_competency_brief(conn: AsyncConnection, competency_id: UUID) -> dict:
    """A competency with its active capabilities: {id, code, name, description, capabilities}."""
    comp = await fetch_required(
        conn,
        "select id, code, name, description from competencies where id = %s and deleted_at is null",
        (competency_id,),
    )
    comp["capabilities"] = await fetch_all(
        conn,
        """
        select id, code, name from capabilities
         where competency_id = %s and is_active and deleted_at is null
         order by sort_order, code
        """,
        (competency_id,),
    )
    return comp


def graded(evidence: dict) -> bool:
    """Whether the evidence carries a value for this student."""
    return evidence["score_status"] == "graded"


async def list_conclusion_evidence(
    conn: AsyncConnection,
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID,
    term_id: UUID,
) -> list[dict]:
    """The published evidences of a class and term that apply to the student and are read against
    at least one criterion of the competency. Only that competency's criteria are attached, and the
    score's feedback is included: it is the teacher's own words about the work."""
    out = await fetch_all(
        conn,
        """
        select a.id, a.title, a.description, a.kind, a.value_scale, a.due_at,
               s.status as score_status, s.raw_value::float8 as raw_value,
               s.max_value::float8 as max_value, l.code as scale_level, s.feedback,
               pe.experience_id
          from assessments a
          left join scores s on s.assessment_id = a.id and s.student_id = %(student)s
                            and s.superseded_at is null and s.deleted_at is null
          left join grade_scale_levels l on l.id = s.scale_level_id
          left join planned_evidences pe on pe.id = a.planned_evidence_id and pe.deleted_at is null
         where a.class_id = %(class)s and a.term_id = %(term)s
           and a.status in ('published', 'closed') and a.deleted_at is null
           and (a.student_id is null or a.student_id = %(student)s)
           and exists (
             select 1 from assessment_criteria ac
               join evaluation_criteria ec on ec.id = ac.criterion_id
              where ac.assessment_id = a.id and ec.competency_id = %(comp)s
                and ec.deleted_at is null)
         order by coalesce(a.due_at, a.created_at), a.id
        """,
        {"class": class_id, "student": student_id, "comp": competency_id, "term": term_id},
    )
    for e in out:
        e["criteria"] = []
    if not out:
        return out
    index = {e["id"]: e for e in out}
    # Capabilities come from evaluation_criterion_capabilities (N:M); a criterion without rows
    # there falls back to its own capability_id.
    for c in await fetch_all(
        conn,
        """
        select ac.assessment_id, ec.id, ec.description,
               coalesce(
                 (select array_agg(ecc.capability_id order by ecc.capability_id)
                    from evaluation_criterion_capabilities ecc
                   where ecc.criterion_id = ec.id and ecc.deleted_at is null),
                 array[ec.capability_id]) as capability_ids
          from assessment_criteria ac
          join evaluation_criteria ec on ec.id = ac.criterion_id
         where ac.assessment_id = any(%s::uuid[]) and ec.competency_id = %s
           and ec.deleted_at is null
         order by ac.assessment_id, ec.sort_order, ec.id
        """,
        (list(index), competency_id),
    ):
        index[c["assessment_id"]]["criteria"].append(
            {
                "id": c["id"],
                "description": c["description"],
                "capability_ids": c["capability_ids"],
            }
        )
    return out


async def list_conclusion_voice_notes(
    conn: AsyncConnection, class_id: UUID, student_id: UUID, term_id: UUID
) -> tuple[list[dict], dict]:
    """The student's swept, usable voice notes of the class in the term, oldest first, and counts
    of the discarded ones and the ones not swept yet (still transcribing or waiting for the
    sweep). Returns (notes, {"discarded": n, "pending": n})."""
    rows = await fetch_all(
        conn,
        """
        select vn.id, vn.recorded_at, cs.topic as session_topic,
               vn.transcript_redacted as redacted, vn.attribution_status as status,
               vn.transcription_status as transcription
          from voice_notes vn
          join class_sessions cs on cs.id = vn.session_id
         where vn.class_id = %s and vn.student_id = %s and cs.term_id = %s
           and vn.deleted_at is null
         order by vn.recorded_at, vn.id
        """,
        (class_id, student_id, term_id),
    )
    counts = {"discarded": 0, "pending": 0}
    out: list[dict] = []
    for r in rows:
        if r["status"] == ATTRIBUTION_DISCARDED:
            counts["discarded"] += 1
        elif r["status"] == ATTRIBUTION_PENDING:
            # Failed or skipped transcriptions will never be swept: they are not "in process",
            # just absent.
            if r["transcription"] not in ("failed", "skipped"):
                counts["pending"] += 1
        elif r["redacted"]:
            out.append(
                {
                    "id": r["id"],
                    "recorded_at": r["recorded_at"],
                    "session_topic": r["session_topic"],
                    "transcript_redacted": r["redacted"],
                }
            )
    return out, counts


async def list_discarded_voice_notes(
    conn: AsyncConnection, class_id: UUID, student_id: UUID, term_id: UUID
) -> list[dict]:
    """The student's discarded notes in a class and term, newest first. Shown to the teacher only
    when discarding them leaves too little evidence; the teacher recorded them, so the original
    transcript is shown."""
    return await fetch_all(
        conn,
        """
        select vn.id, vn.recorded_at, vn.duration_ms, vn.transcript, vn.discard_reason
          from voice_notes vn
          join class_sessions cs on cs.id = vn.session_id
         where vn.class_id = %s and vn.student_id = %s and cs.term_id = %s
           and vn.deleted_at is null and vn.attribution_status = 'discarded'
         order by vn.recorded_at desc, vn.id
        """,
        (class_id, student_id, term_id),
    )


async def list_earlier_term_conclusions(
    conn: AsyncConnection, student_id: UUID, competency_id: UUID, term_id: UUID
) -> list[dict]:
    """Oldest first, the student's live level and conclusion for the competency in the terms before
    term_id in the same academic year. A justification for consecutive C needs them."""
    rows = await fetch_all(
        conn,
        """
        select pt.name as term_name, pt.sequence, l.code as level, dc.body
          from terms t
          join terms pt on pt.academic_year_id = t.academic_year_id
                       and coalesce(pt.stage, '') = coalesce(t.stage, '')
                       and pt.sequence < t.sequence and pt.deleted_at is null
          left join competency_term_levels ctl
                 on ctl.term_id = pt.id and ctl.student_id = %(student)s
                and ctl.competency_id = %(comp)s
                and ctl.superseded_at is null and ctl.deleted_at is null
          left join grade_scale_levels l on l.id = ctl.scale_level_id
          left join descriptive_conclusions dc
                 on dc.term_id = pt.id and dc.student_id = %(student)s
                and dc.competency_id = %(comp)s
                and dc.superseded_at is null and dc.deleted_at is null
         where t.id = %(term)s
         order by pt.sequence
        """,
        {"student": student_id, "comp": competency_id, "term": term_id},
    )
    return [r for r in rows if r["level"] is not None or r["body"] is not None]


async def roster_names(
    conn: AsyncConnection, class_id: UUID, student_id: UUID, today: date
) -> list[dict]:
    """Every name of the students on a class's roster today and of the given student, for the
    final check that a proposed conclusion names no one."""
    ids = await roster_as_of(conn, class_id, today)
    return await student_names(conn, [*ids, student_id])
