"""Evidence (assessments) and scores.

A piece of evidence carries no weight: under RVM 094-2020 a mark informs the teacher's
judgement of the criterios and never feeds a final grade arithmetically.
"""

from uuid import UUID

from psycopg import AsyncConnection

import domain
from db import fetch_one, fetch_required
from errors import AppError


def _bad(code: str, message: str) -> AppError:
    return AppError(400, code, message)


async def create_assessment(
    conn: AsyncConnection,
    *,
    class_id: UUID,
    term_id: UUID,
    teacher_id: UUID,
    student_id: UUID | None,
    title: str,
    kind: str,
    value_scale: str,
    max_score: float | None,
    due_at: str | None,
    criterion_ids: list[UUID],
) -> UUID:
    """File one piece of evidence. student_id None means the whole class; set, it is
    evidence for that student alone. At least one criterio is required: that is how the
    evidence reaches a competencia."""
    if not criterion_ids:
        raise _bad(
            "criteria_required",
            "an evidence needs at least one criterio: that is how it reaches a competencia",
        )
    if student_id is not None:
        # The student must be on this class's roster, or a teacher could file evidence against
        # a student from another section by id.
        row = await fetch_required(
            conn,
            """
            select exists (
              select 1 from classes cl
                join section_memberships sm on sm.section_id = cl.section_id
               where cl.id = %(class)s and sm.student_id = %(student)s
                 and sm.joined_on <= current_date
                 and (sm.left_on is null or sm.left_on > current_date)
                 and sm.deleted_at is null and cl.deleted_at is null
            ) as ok
            """,
            {"class": class_id, "student": student_id},
        )
        if not row["ok"]:
            raise _bad("student_not_in_class", "that student is not on this class's roster")

    row = await fetch_required(
        conn,
        """
        insert into assessments (tenant_id, class_id, term_id, student_id,
                                  title, kind, value_scale, max_score, due_at,
                                  status, published_at, created_by_id)
        values (app.current_tenant_id(), %s, %s, %s, %s, %s, %s, %s, %s::timestamptz,
                'published', now(), %s)
        returning id
        """,
        (class_id, term_id, student_id, title, kind, value_scale, max_score, due_at, teacher_id),
    )
    assessment_id = row["id"]
    await _link_assessment_criteria(conn, class_id, term_id, assessment_id, criterion_ids)
    return assessment_id


async def _link_assessment_criteria(
    conn: AsyncConnection,
    class_id: UUID,
    term_id: UUID,
    assessment_id: UUID,
    criterion_ids: list[UUID],
) -> None:
    """Record which criterios an assessment evidences. Every criterio must belong to a
    competencia of the class's área; a criterio of an experiencia must also be one
    list_evidence_criteria offers (accepted, of a planned experiencia of this class and
    term), or a teacher could tag evidence with another class's criterio or a draft."""
    row = await fetch_required(
        conn,
        """
        select count(*) as n
          from evaluation_criteria ec
          join competencies c on c.id = ec.competency_id
          join courses co on co.subject_id = c.subject_id
          join classes cl on cl.course_id = co.id
         where cl.id = %(class)s and ec.id = any(%(ids)s::uuid[])
           and ec.deleted_at is null and c.deleted_at is null and cl.deleted_at is null
           and (ec.experience_id is null or (
                 ec.accepted_at is not null and exists (
                   select 1 from learning_experiences le
                    where le.id = ec.experience_id and le.class_id = %(class)s
                      and le.term_id = %(term)s
                      and le.status = 'planificada' and le.deleted_at is null)))
        """,
        {"class": class_id, "ids": criterion_ids, "term": term_id},
    )
    if row["n"] != len(criterion_ids):
        raise _bad(
            "criterion_not_in_class",
            "one of those criterios does not belong to this class's área or to a planned"
            " experiencia of this class and period",
        )
    await conn.execute(
        """
        insert into assessment_criteria (tenant_id, assessment_id, criterion_id)
        select app.current_tenant_id(), %s, unnest(%s::uuid[])
        """,
        (assessment_id, criterion_ids),
    )


async def delete_assessment(conn: AsyncConnection, assessment_id: UUID) -> dict:
    """Soft-delete a piece of evidence; its scores stay in the student's history.
    Returns {class_id, term_id, student_id} for the audit event."""
    row = await fetch_one(
        conn,
        """
        update assessments set deleted_at = now()
         where id = %s and deleted_at is null
        returning class_id, term_id, student_id
        """,
        (assessment_id,),
    )
    if row is None:
        raise AppError(404, "assessment_not_found", "that evidence no longer exists")
    return row


def _check_value(
    value_scale: str, max_score: float | None, status: str, raw: float | None, level: str | None
) -> None:
    """Reject a value that does not fit the evidence's scale before it reaches the database,
    so the teacher gets a message instead of a constraint name."""
    if status != domain.SCORE_GRADED:
        if raw is not None or level is not None:
            raise _bad("value_not_allowed", "a status other than graded carries no value")
        return
    if value_scale == domain.VALUE_SCALE_NUMERIC:
        if level is not None:
            raise _bad("level_on_numeric", "this evidence is valued with a mark, not a level")
        if raw is None:
            raise _bad("value_required", "a graded score needs a mark")
        if raw < 0 or (max_score is not None and raw > max_score):
            raise _bad(
                "mark_out_of_range",
                "the mark must be between 0 and the maximum of this evidence",
            )
    elif value_scale == domain.VALUE_SCALE_ORDINAL:
        if raw is not None:
            raise _bad("mark_on_ordinal", "this evidence is valued with a level, not a mark")
        if level is None:
            raise _bad("value_required", "a graded score needs a level")


async def _level_id(conn: AsyncConnection, code: str) -> UUID:
    """Resolve an AD/A/B/C code to the tenant's ordinal scale level."""
    row = await fetch_one(
        conn,
        """
        select l.id
          from grade_scale_levels l
          join grade_scales s on s.id = l.scale_id and s.tenant_id = l.tenant_id
         where s.kind = 'ordinal' and l.code = %s
           and l.deleted_at is null and s.deleted_at is null
        """,
        (code,),
    )
    if row is None:
        raise _bad("invalid_level", "level must be one of AD, A, B, C")
    return row["id"]


async def _assessment_scale(conn: AsyncConnection, assessment_id: UUID) -> tuple[str, float | None]:
    row = await fetch_one(
        conn,
        "select value_scale, max_score from assessments where id = %s and deleted_at is null",
        (assessment_id,),
    )
    if row is None:
        raise AppError(404, "assessment_not_found", "that evidence no longer exists")
    return row["value_scale"], _float(row["max_score"])


def _float(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


async def create_score(
    conn: AsyncConnection,
    assessment_id: UUID,
    student_id: UUID,
    teacher_id: UUID,
    status: str,
    raw_value: float | None,
    level: str | None,
) -> tuple[UUID, UUID, UUID]:
    """Record the first valuation of a student on an evidence: (id, class_id, term_id)."""
    value_scale, max_score = await _assessment_scale(conn, assessment_id)
    _check_value(value_scale, max_score, status, raw_value, level)
    scale_level = await _level_id(conn, level) if level is not None else None
    # max_value comes from the assessment, so it's always the denominator the score was
    # recorded out of, even if the assessment's own max changes later.
    row = await fetch_required(
        conn,
        """
        insert into scores (tenant_id, assessment_id, student_id, status, raw_value, max_value,
                             scale_level_id, source, recorded_by_id)
        select app.current_tenant_id(), %(a)s, %(student)s, %(status)s, %(raw)s, a.max_score,
               %(level)s, 'manual', %(teacher)s
          from assessments a where a.id = %(a)s
        returning id, class_id, term_id
        """,
        {
            "a": assessment_id,
            "student": student_id,
            "status": status,
            "raw": raw_value,
            "level": scale_level,
            "teacher": teacher_id,
        },
    )
    return row["id"], row["class_id"], row["term_id"]


async def correct_score(
    conn: AsyncConnection,
    score_id: UUID,
    teacher_id: UUID,
    raw_value: float | None,
    level: str | None,
    status: str | None,
) -> tuple[UUID, UUID, UUID, UUID]:
    """The supersede protocol: stamp superseded_at on the live row first, then insert the
    replacement with supersedes_id set, in that order and one transaction, because
    scores_live_key is a partial unique index and cannot be deferred. A correction that
    names nothing inherits the old value, except that a status other than graded carries no
    value. Returns (new_score_id, student_id, class_id, term_id)."""
    old = await fetch_one(
        conn,
        """
        select s.assessment_id, s.student_id, s.status, s.raw_value, l.code as level
          from scores s
          left join grade_scale_levels l on l.id = s.scale_level_id
         where s.id = %s and s.superseded_at is null and s.deleted_at is null
        """,
        (score_id,),
    )
    if old is None:
        raise AppError(409, "already_superseded", "score already superseded; reload and try again")
    value_scale, max_score = await _assessment_scale(conn, old["assessment_id"])

    new_status = status if status is not None else old["status"]
    new_raw = raw_value if raw_value is not None else _float(old["raw_value"])
    new_level = level if level is not None else old["level"]
    # not_submitted and its siblings carry no value; keeping the old mark would leave a number
    # on a row that says nothing was handed in.
    if new_status != domain.SCORE_GRADED:
        new_raw, new_level = None, None
    _check_value(value_scale, max_score, new_status, new_raw, new_level)
    scale_level = await _level_id(conn, new_level) if new_level is not None else None

    await conn.execute("update scores set superseded_at = now() where id = %s", (score_id,))
    row = await fetch_required(
        conn,
        """
        insert into scores (tenant_id, assessment_id, student_id, status, raw_value, max_value,
                             scale_level_id, source, recorded_by_id, supersedes_id)
        select app.current_tenant_id(), %(a)s, %(student)s, %(status)s, %(raw)s, a.max_score,
               %(level)s, 'manual', %(teacher)s, %(old)s
          from assessments a where a.id = %(a)s
        returning id, class_id, term_id
        """,
        {
            "a": old["assessment_id"],
            "student": old["student_id"],
            "status": new_status,
            "raw": new_raw,
            "level": scale_level,
            "teacher": teacher_id,
            "old": score_id,
        },
    )
    return row["id"], old["student_id"], row["class_id"], row["term_id"]
