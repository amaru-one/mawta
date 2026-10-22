"""Niveles de logro and conclusiones descriptivas."""

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

import domain
from db import fetch_all, fetch_one, fetch_required
from errors import AppError


def classify_conclusion_requirement(
    inclusion_support: bool, stage: str, cycle: str, level_code: str | None, consecutive_c: bool
) -> str:
    """Why a conclusión descriptiva is (or isn't) mandatory, per the grade-level-dependent
    obligatoriedad: inclusion support is mandatory every period regardless of level or grade;
    Inicial Ciclo I requires one for every competencia regardless of level; otherwise the level
    itself decides by nivel educativo (C in Secundaria/Primaria/Inicial Ciclo II, B in
    Primaria/Inicial Ciclo II, A only in Inicial Ciclo II). C also carries the stronger
    consecutive_c classification when the competency was C in the immediately preceding period
    too (RVM 048-2024, 5.1.1.3 p.3)."""
    if inclusion_support:
        return domain.CONCLUSION_INCLUSION_SUPPORT
    if stage == domain.STAGE_INICIAL and cycle == domain.CYCLE_I:
        return domain.CONCLUSION_CYCLE_I_MANDATORY
    if level_code is None:
        return domain.CONCLUSION_OPTIONAL
    inicial_cycle_ii = stage == domain.STAGE_INICIAL and cycle == domain.CYCLE_II
    if level_code == domain.LEVEL_C:
        return domain.CONCLUSION_CONSECUTIVE_C if consecutive_c else domain.CONCLUSION_LEVEL_C
    if level_code == domain.LEVEL_B and (stage == domain.STAGE_PRIMARIA or inicial_cycle_ii):
        return domain.CONCLUSION_LEVEL_B
    if level_code == domain.LEVEL_A and inicial_cycle_ii:
        return domain.CONCLUSION_LEVEL_A
    return domain.CONCLUSION_OPTIONAL


async def stage_and_cycle(conn: AsyncConnection[DictRow], class_id: UUID) -> tuple[str, str]:
    row = await fetch_required(
        conn,
        """
        select gl.stage, coalesce(gl.cycle, '') as cycle
          from classes cl
          join courses co on co.id = cl.course_id
          join grade_levels gl on gl.id = co.grade_level_id
         where cl.id = %s
        """,
        (class_id,),
    )
    return row["stage"], row["cycle"]


async def expected_standards(
    conn: AsyncConnection[DictRow], cycle: str, competency_ids: list[UUID]
) -> dict[UUID, dict[str, Any]]:
    """The learning standard each competency expects at the end of `cycle` (CNEB: the level is
    judged against the standard of the cycle's expected level), keyed by competency id. A
    competency without a standard at that level is left out."""
    if not cycle or not competency_ids:
        return {}
    rows = await fetch_all(
        conn,
        """
        select s.competency_id, s.level, s.official_text
          from standard_level_mappings m
          join learning_standards s on s.level = m.expected_level
         where m.modality = 'ebr' and m.cycle = %s and m.deleted_at is null
           and s.competency_id = any(%s) and s.deleted_at is null
        """,
        (cycle, competency_ids),
    )
    return {
        r["competency_id"]: {"level": r["level"], "cycle": cycle, "text": r["official_text"]}
        for r in rows
    }


async def list_class_competency_levels(
    conn: AsyncConnection[DictRow], class_id: UUID, student_id: UUID, term_id: UUID
) -> list[dict[str, Any]] | None:
    """Every competency of the class's subject with this student's asserted level and
    conclusion for the term. There is deliberately no suggested level."""
    stage, cycle = await stage_and_cycle(conn, class_id)
    rows = await fetch_all(
        conn,
        """
        with cls as (
          select co.subject_id
            from classes cl
            join courses co on co.id = cl.course_id
           where cl.id = %(class)s
        ),
        lvl as (
          select ctl.competency_id, ctl.scale_level_id, ctl.asserted_at,
                 ctl.term_id, l.code as level_code
            from competency_term_levels ctl
            join grade_scale_levels l on l.id = ctl.scale_level_id
           where ctl.student_id = %(student)s and ctl.term_id = %(term)s
             and ctl.superseded_at is null and ctl.deleted_at is null
        ),
        -- Was this competency at C in the immediately preceding period (same
        -- academic year, sequence - 1)?
        prev_c as (
          select ctl.competency_id
            from competency_term_levels ctl
            join terms pt on pt.id = ctl.term_id
            join terms t on t.id = %(term)s
            join grade_scale_levels l on l.id = ctl.scale_level_id
           where ctl.student_id = %(student)s
             and pt.academic_year_id = t.academic_year_id
             and pt.sequence = t.sequence - 1
             and l.code = %(c)s
             and ctl.superseded_at is null and ctl.deleted_at is null
        ),
        concl as (
          select competency_id, body, status, authored_at
            from descriptive_conclusions
           where student_id = %(student)s and term_id = %(term)s
             and superseded_at is null and deleted_at is null
        ),
        -- Last change to any score of the student in this term, per competency. Scores are
        -- append-only: a new mark, a correction and a removal each touch created_at,
        -- superseded_at or deleted_at. greatest() ignores nulls.
        grades as (
          select ec.competency_id,
                 max(greatest(s.created_at, s.superseded_at, s.deleted_at)) as last_change
            from scores s
            join assessment_criteria ac on ac.assessment_id = s.assessment_id
             and ac.deleted_at is null
            join evaluation_criteria ec on ec.id = ac.criterion_id
           where s.student_id = %(student)s and s.term_id = %(term)s
           group by ec.competency_id
        )
        select c.id as competency_id, c.code, c.name, c.kind, c.subject_id,
               lvl.level_code as level, lvl.scale_level_id as level_id,
               to_char(lvl.asserted_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                 as asserted_at,
               s.inclusion_support, prev_c.competency_id is not null as consecutive_c,
               concl.body as conclusion_body, concl.status as conclusion_status,
               coalesce(grades.last_change > concl.authored_at, false) as grades_changed
          from competencies c
          cross join students s
          left join lvl on lvl.competency_id = c.id
          left join prev_c on prev_c.competency_id = c.id
          left join concl on concl.competency_id = c.id
          left join grades on grades.competency_id = c.id
         where s.id = %(student)s
           and c.subject_id = (select subject_id from cls)
           and c.is_active and c.deleted_at is null
         order by c.sort_order, c.code
        """,
        {"class": class_id, "student": student_id, "term": term_id, "c": domain.LEVEL_C},
    )
    standards = await expected_standards(conn, cycle, [r["competency_id"] for r in rows])
    out: list[dict[str, Any]] = []
    for r in rows:
        requirement = classify_conclusion_requirement(
            r["inclusion_support"], stage, cycle, r["level"], r["consecutive_c"]
        )
        out.append(
            {
                "competency_id": r["competency_id"],
                "code": r["code"],
                "name": r["name"],
                "kind": r["kind"],
                "subject_id": r["subject_id"],
                "level": r["level"],
                "level_id": r["level_id"],
                "asserted_at": r["asserted_at"],
                "conclusion_required": requirement != domain.CONCLUSION_OPTIONAL,
                "conclusion_requirement": requirement,
                "conclusion_body": r["conclusion_body"],
                "conclusion_status": r["conclusion_status"],
                "grades_changed": r["grades_changed"],
                "standard": standards.get(r["competency_id"]),
            }
        )
    return out or None


async def assert_competency_level(
    conn: AsyncConnection[DictRow],
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID,
    term_id: UUID,
    teacher_id: UUID,
    level_code: str,
    note: str | None,
) -> UUID:
    """Record a teacher's nivel de logro for one competency in one period, superseding any level
    already on record. The only way an official level is ever written; nothing is derived into
    it: under RVM 094-2020 it is the teacher's judgement of the period's evidence."""
    level = await fetch_one(
        conn,
        """
        select l.id
          from grade_scale_levels l
          join grade_scales g on g.id = l.scale_id
         where g.kind = 'ordinal' and l.code = %s
           and l.deleted_at is null and g.deleted_at is null
         limit 1
        """,
        (level_code,),
    )
    if level is None:
        raise AppError(400, "unknown_level", "level must be one of AD, A, B or C")

    old = await fetch_one(
        conn,
        """
        update competency_term_levels set superseded_at = now()
         where student_id = %s and competency_id = %s and term_id = %s
           and superseded_at is null and deleted_at is null
        returning id
        """,
        (student_id, competency_id, term_id),
    )
    row = await fetch_required(
        conn,
        """
        insert into competency_term_levels
          (tenant_id, student_id, competency_id, academic_year_id, term_id, class_id,
           scale_level_id, asserted_by_id, note, supersedes_id)
        select app.current_tenant_id(), %(student)s, %(comp)s, c.academic_year_id, %(term)s,
               %(class)s, %(level)s, %(teacher)s, %(note)s, %(old)s
          from classes c where c.id = %(class)s
        returning id
        """,
        {
            "student": student_id,
            "comp": competency_id,
            "term": term_id,
            "class": class_id,
            "level": level["id"],
            "teacher": teacher_id,
            "note": note,
            "old": old["id"] if old else None,
        },
    )
    return row["id"]


def check_conclusion_length(body: str) -> None:
    """Reject a normalized conclusion SIAGIE would not accept, telling the teacher how far off."""
    n = domain.conclusion_length(body)
    if n < domain.CONCLUSION_MIN_CHARS:
        raise AppError(
            422,
            "conclusion_too_short",
            f"La conclusión tiene {n} caracteres; SIAGIE pide al menos"
            f" {domain.CONCLUSION_MIN_CHARS}.",
        )
    if n > domain.CONCLUSION_MAX_CHARS:
        raise AppError(
            422,
            "conclusion_too_long",
            f"La conclusión tiene {n} caracteres; SIAGIE acepta como máximo"
            f" {domain.CONCLUSION_MAX_CHARS}. Acórtala en {n - domain.CONCLUSION_MAX_CHARS}.",
        )


async def conclusion_requirement(
    conn: AsyncConnection[DictRow],
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID,
    term_id: UUID,
) -> str:
    stage, cycle = await stage_and_cycle(conn, class_id)
    inclusion = (
        await fetch_required(
            conn, "select inclusion_support from students where id = %s", (student_id,)
        )
    )["inclusion_support"]
    level = await fetch_one(
        conn,
        """
        select l.code from competency_term_levels ctl
          join grade_scale_levels l on l.id = ctl.scale_level_id
         where ctl.student_id = %s and ctl.competency_id = %s and ctl.term_id = %s
           and ctl.superseded_at is null and ctl.deleted_at is null
        """,
        (student_id, competency_id, term_id),
    )
    level_code = level["code"] if level else None
    consecutive_c = False
    if level_code == domain.LEVEL_C:
        consecutive_c = (
            await fetch_required(
                conn,
                """
                select exists (
                  select 1 from competency_term_levels ctl
                    join terms pt on pt.id = ctl.term_id
                    join terms t on t.id = %(term)s
                    join grade_scale_levels l on l.id = ctl.scale_level_id
                   where ctl.student_id = %(student)s and ctl.competency_id = %(comp)s
                     and pt.academic_year_id = t.academic_year_id
                     and pt.sequence = t.sequence - 1
                     and l.code = %(c)s
                     and ctl.superseded_at is null and ctl.deleted_at is null
                ) as ok
                """,
                {
                    "term": term_id,
                    "student": student_id,
                    "comp": competency_id,
                    "c": domain.LEVEL_C,
                },
            )
        )["ok"]
    return classify_conclusion_requirement(inclusion, stage, cycle, level_code, consecutive_c)


async def upsert_conclusion(
    conn: AsyncConnection[DictRow],
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID,
    term_id: UUID,
    teacher_id: UUID,
    body: str,
    status: str,
    generation_id: UUID | None,
) -> UUID:
    """Write a conclusión descriptiva, superseding any previous one for the same competency and
    period. `requirement` is derived here, never taken from the request. The body is stored as
    SIAGIE receives it and must fit its 10 to 350 characters, draft or final.

    generation_id, when set, is the Mawta proposal the teacher started from: it must be a
    completed conclusions generation for this same student, competency and term. The text is
    still the teacher's. When that proposal read at least one voice note,
    generated_from_voice_notes is set; the flag is read from the generation, not the request.
    """
    body = domain.normalize_conclusion(body)
    check_conclusion_length(body)

    from_voice_notes = False
    if generation_id is not None:
        gen = await fetch_one(
            conn,
            """
            select true as ok,
                   coalesce(jsonb_typeof(result -> 'used_voice_note_ids') = 'array'
                            and jsonb_array_length(result -> 'used_voice_note_ids') > 0,
                            false) as used_voice_notes
              from agent_generations
             where id = %s and agent = 'conclusions' and status = 'completed'
               and student_id = %s and competency_id = %s and term_id = %s
            """,
            (generation_id, student_id, competency_id, term_id),
        )
        if gen is None:
            raise AppError(
                422,
                "generation_mismatch",
                "La propuesta de Mawta no corresponde a esta competencia y periodo.",
            )
        from_voice_notes = gen["used_voice_notes"]

    requirement = await conclusion_requirement(conn, class_id, student_id, competency_id, term_id)

    old = await fetch_one(
        conn,
        """
        update descriptive_conclusions set superseded_at = now()
         where student_id = %s and competency_id = %s and term_id = %s
           and superseded_at is null and deleted_at is null
        returning id
        """,
        (student_id, competency_id, term_id),
    )
    row = await fetch_required(
        conn,
        """
        insert into descriptive_conclusions
          (tenant_id, student_id, competency_id, academic_year_id, term_id, class_id, body,
           requirement, status, authored_by_id, supersedes_id, generation_id,
           generated_from_voice_notes)
        select app.current_tenant_id(), %(student)s, %(comp)s, c.academic_year_id, %(term)s,
               %(class)s, %(body)s, %(requirement)s, %(status)s, %(teacher)s, %(old)s,
               %(generation)s, %(voice)s
          from classes c where c.id = %(class)s
        returning id
        """,
        {
            "student": student_id,
            "comp": competency_id,
            "term": term_id,
            "class": class_id,
            "body": body,
            "requirement": requirement,
            "status": status,
            "teacher": teacher_id,
            "old": old["id"] if old else None,
            "generation": generation_id,
            "voice": from_voice_notes,
        },
    )
    return row["id"]
