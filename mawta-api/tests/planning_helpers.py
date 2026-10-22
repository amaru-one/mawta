"""Shared fixtures for the planning tests.

The tests commit real rows into one database the whole session shares. So every test that writes
plans does it on a class of its own (plan_class), which removes everything planned on it when
the test ends. What the fixture lacks for planning (the 5S cycle, capabilities, performances,
non-teaching days) is added by ensure_planning_curriculum with fixed ids and "on conflict do
nothing", so any test can call it and none of them owns it.
"""

import uuid
from datetime import date, timedelta
from typing import Any, LiteralString, cast

import psycopg
from psycopg.rows import DictRow

from tests.conftest import FX

PLAN_CAP_C1A = uuid.UUID("a0000000-0000-4000-8000-000000000402")
PLAN_CAP_C1B = uuid.UUID("a0000000-0000-4000-8000-000000000403")
PLAN_PERF_C1A = uuid.UUID("a0000000-0000-4000-8000-000000000404")
PLAN_PERF_C1B = uuid.UUID("a0000000-0000-4000-8000-000000000405")
PLAN_PERF_C2 = uuid.UUID("a0000000-0000-4000-8000-000000000406")
PLAN_PERF_C1_OF_4S = uuid.UUID("a0000000-0000-4000-8000-000000000407")
PLAN_GRADE_4S = uuid.UUID("a0000000-0000-4000-8000-000000000401")
PLAN_SUBJECT_COM = uuid.UUID("a0000000-0000-4000-8000-000000000408")
PLAN_COMPET_COM = uuid.UUID("a0000000-0000-4000-8000-000000000409")
PLAN_LEVEL_MAP = uuid.UUID("a0000000-0000-4000-8000-00000000040a")
PLAN_STD_C1 = uuid.UUID("a0000000-0000-4000-8000-00000000040b")
PLAN_STD_C2 = uuid.UUID("a0000000-0000-4000-8000-00000000040c")
PLAN_HOLIDAY = "2026-06-29"
PLAN_VACATION_IN = "2026-07-20"
PLAN_VACATION_OUT = "2026-07-24"


async def admin_script(
    admin: psycopg.AsyncConnection[DictRow], script: str, **variables: object
) -> None:
    """Run a multi-statement script on the admin connection. Each {{name}} becomes the value as a
    quoted literal; the values are this module's own ids and dates, never input."""
    for name, value in variables.items():
        literal = "'" + str(value).replace("'", "''") + "'"
        script = script.replace("{{" + name + "}}", literal)
    await admin.execute(cast(LiteralString, script))


async def ensure_planning_curriculum(admin: psycopg.AsyncConnection[DictRow]) -> None:
    await admin_script(
        admin,
        """
        update grade_levels set cycle = 'ciclo_vii' where id = {{grade}} and cycle is null;

        insert into standard_level_mappings (id, tenant_id, modality, cycle, expected_level)
        values ({{mapping}}, {{tenant}}, 'ebr', 'ciclo_vii', 7) on conflict do nothing;

        insert into learning_standards (id, tenant_id, competency_id, level, official_text) values
          ({{stdC1}}, {{tenant}}, {{c1}}, 7,
           'Resuelve problemas referidos a las relaciones entre cantidades.'),
          ({{stdC2}}, {{tenant}}, {{c2}}, 7,
           'Resuelve problemas de regularidad, equivalencia y cambio.')
        on conflict do nothing;

        insert into capabilities (id, tenant_id, competency_id, code, name, sort_order) values
          ({{capC1a}}, {{tenant}}, {{c1}}, 'MAT-C1-CAP1', 'Traduce cantidades a expresiones numéricas', 1),
          ({{capC1b}}, {{tenant}}, {{c1}}, 'MAT-C1-CAP2',
           'Comunica su comprensión sobre los números y las operaciones', 2)
        on conflict do nothing;

        insert into grade_levels (id, tenant_id, code, label, long_label, ordinal, stage, cycle)
        values ({{grade4S}}, {{tenant}}, '4S', '4to', 'Cuarto de secundaria', 10, 'secundaria', 'ciclo_vii')
        on conflict do nothing;

        insert into grade_level_performances
          (id, tenant_id, competency_id, grade_level_id, sort_order, official_text, en_proceso,
           expected_standard_level, suggested_capability_id) values
          ({{perfC1a}}, {{tenant}}, {{c1}}, {{grade}}, 1,
           'Establece relaciones entre datos y acciones de comparar cantidades.', false, 7, {{capC1a}}),
          ({{perfC1b}}, {{tenant}}, {{c1}}, {{grade}}, 2,
           'Expresa con diversas representaciones su comprensión del número.', false, 7, {{capC1b}}),
          ({{perfC2}}, {{tenant}}, {{c2}}, {{grade}}, 1,
           'Establece relaciones entre datos, valores desconocidos y regularidades.', false, 7, null),
          ({{perf4S}}, {{tenant}}, {{c1}}, {{grade4S}}, 1, 'Desempeño de cuarto grado.', true, 7, null)
        on conflict do nothing;

        insert into subjects (id, tenant_id, code, name)
        values ({{subjectCom}}, {{tenant}}, 'COM', 'Comunicación') on conflict do nothing;
        insert into competencies (id, tenant_id, subject_id, code, name, kind)
        values ({{competCom}}, {{tenant}}, {{subjectCom}}, 'COM-C1',
                'Se comunica oralmente en su lengua materna', 'area')
        on conflict do nothing;

        insert into non_teaching_days (tenant_id, academic_year_id, day, kind, label)
        values ({{tenant}}, {{year}}, {{holiday}}, 'feriado', 'San Pedro y San Pablo')
        on conflict do nothing;
        insert into non_teaching_days (tenant_id, academic_year_id, day, kind, label)
        select {{tenant}}, {{year}}, g.d::date, 'vacaciones', 'Vacaciones de medio año'
          from generate_series({{vacIn}}::date, {{vacOut}}::date, interval '1 day') as g(d)
        on conflict do nothing;
        """,
        grade=FX.grade_level,
        mapping=PLAN_LEVEL_MAP,
        tenant=FX.tenant_a,
        stdC1=PLAN_STD_C1,
        stdC2=PLAN_STD_C2,
        capC1a=PLAN_CAP_C1A,
        capC1b=PLAN_CAP_C1B,
        c1=FX.competency_c1,
        c2=FX.competency_c2,
        grade4S=PLAN_GRADE_4S,
        perfC1a=PLAN_PERF_C1A,
        perfC1b=PLAN_PERF_C1B,
        perfC2=PLAN_PERF_C2,
        perf4S=PLAN_PERF_C1_OF_4S,
        subjectCom=PLAN_SUBJECT_COM,
        competCom=PLAN_COMPET_COM,
        year=FX.year_a,
        holiday=PLAN_HOLIDAY,
        vacIn=PLAN_VACATION_IN,
        vacOut=PLAN_VACATION_OUT,
    )


async def create_plan_class(admin: psycopg.AsyncConnection[DictRow]) -> tuple[uuid.UUID, uuid.UUID]:
    """A Matemática 5to class of its own for Quispe, with a Monday/Wednesday timetable over
    Bimestre II, a double block on 2026-05-20 and a cancelled session on Friday 2026-05-22.
    Returns (class_id, section_id)."""
    await ensure_planning_curriculum(admin)
    section_id, class_id = uuid.uuid4(), uuid.uuid4()
    label = "P" + str(section_id)[:6]
    await admin_script(
        admin,
        """
        insert into sections (id, tenant_id, academic_year_id, grade_level_id, label, name)
        values ({{section}}, {{tenant}}, {{year}}, {{grade}}, {{label}}, {{label}});
        insert into classes (id, tenant_id, academic_year_id, grade_level_id, course_id, section_id,
                             code, name)
        values ({{class}}, {{tenant}}, {{year}}, {{grade}}, {{course}}, {{section}}, {{label}},
                'Matemática ' || {{label}});
        insert into class_teachers (tenant_id, class_id, teacher_id, role, starts_on)
        values ({{tenant}}, {{class}}, {{teacher}}, 'titular', '2026-03-01');
        insert into class_schedules (tenant_id, class_id, weekday, starts_at, ends_at, effective_from)
        values ({{tenant}}, {{class}}, 1, time '08:00', time '09:30', '2026-03-01'),
               ({{tenant}}, {{class}}, 3, time '08:00', time '09:30', '2026-03-01');

        insert into class_sessions (tenant_id, academic_year_id, class_id, term_id, session_date,
                                    scheduled_start_at, scheduled_end_at, status)
        select {{tenant}}, {{year}}, {{class}}, {{term}}, g.d::date,
               (g.d::date + time '08:00') at time zone 'America/Lima',
               (g.d::date + time '09:30') at time zone 'America/Lima', 'scheduled'
          from generate_series('2026-05-18'::date, '2026-07-31'::date, interval '1 day') as g(d)
         where extract(isodow from g.d) in (1, 3);
        insert into class_sessions (tenant_id, academic_year_id, class_id, term_id, session_date,
                                    scheduled_start_at, scheduled_end_at, status)
        values ({{tenant}}, {{year}}, {{class}}, {{term}}, '2026-05-20',
                '2026-05-20 10:00-05', '2026-05-20 11:00-05', 'scheduled'),
               ({{tenant}}, {{year}}, {{class}}, {{term}}, '2026-05-22',
                '2026-05-22 08:00-05', '2026-05-22 09:30-05', 'cancelled');
        """,
        section=section_id,
        **{"class": class_id},
        tenant=FX.tenant_a,
        year=FX.year_a,
        grade=FX.grade_level,
        label=label,
        course=FX.course_mat,
        teacher=FX.teacher_quispe,
        term=FX.term_ii,
    )
    return class_id, section_id


async def drop_plan_class(
    admin: psycopg.AsyncConnection[DictRow], class_id: uuid.UUID, section_id: uuid.UUID
) -> None:
    exp = f"(select id from learning_experiences where class_id = '{class_id}')"
    # One script of many statements, which psycopg cannot run with bound parameters; the
    # interpolated values are UUIDs this module created.
    script = f"""
        delete from jobs where kind = 'agent.generate' and payload->>'generation_id' in
          (select id::text from agent_generations where class_id = '{class_id}');
        delete from agent_generations where class_id = '{class_id}';
        delete from scores where assessment_id in
          (select a.id from assessments a join planned_evidences pe on pe.id = a.planned_evidence_id
            where pe.experience_id in {exp});
        delete from assessment_criteria where assessment_id in
          (select a.id from assessments a join planned_evidences pe on pe.id = a.planned_evidence_id
            where pe.experience_id in {exp});
        delete from assessments where planned_evidence_id in
          (select id from planned_evidences where experience_id in {exp});
        update planned_evidences set session_entry_id = null where experience_id in {exp};
        update session_outline_entries set planned_evidence_id = null where experience_id in {exp};
        delete from planned_evidence_criteria
         where evidence_id in (select id from planned_evidences where experience_id in {exp});
        delete from evaluation_criterion_capabilities
         where criterion_id in (select id from evaluation_criteria where experience_id in {exp});
        delete from evaluation_criteria where experience_id in {exp};
        delete from planned_evidences where experience_id in {exp};
        delete from session_outline_entries where experience_id in {exp};
        delete from experience_competencies where experience_id in {exp};
        delete from learning_experiences where class_id = '{class_id}';
        delete from class_sessions where class_id = '{class_id}';
        delete from class_schedules where class_id = '{class_id}';
        delete from class_teachers where class_id = '{class_id}';
        delete from classes where id = '{class_id}';
        delete from section_memberships where section_id = '{section_id}';
        delete from sections where id = '{section_id}';
        """
    await admin.execute(cast(LiteralString, script))


def expected_class_dates(from_: str, to: str) -> list[str]:
    """plan_class's timetable seen through the class-date rule: Mondays and Wednesdays in
    [from, to], minus the non-teaching days."""
    start, end = date.fromisoformat(from_), date.fromisoformat(to)
    vac_from, vac_to = date.fromisoformat(PLAN_VACATION_IN), date.fromisoformat(PLAN_VACATION_OUT)
    out = []
    day = start
    while day <= end:
        if day.isoweekday() in (1, 3) and day.isoformat() != PLAN_HOLIDAY:
            if not vac_from <= day <= vac_to:
                out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def experience_body(starts_on: str, ends_on: str, *competencies: uuid.UUID) -> dict[str, Any]:
    return {
        "term_id": str(FX.term_ii),
        "title": "La tiendita escolar",
        "idea_text": "Armar una tiendita y calcular vueltos",
        "situation_text": "La I.E. organiza una feria",
        "starts_on": starts_on,
        "ends_on": ends_on,
        "competency_ids": [str(c) for c in competencies],
    }


def criterion_body(competency_id: uuid.UUID, performance_id: uuid.UUID, *capabilities: uuid.UUID):
    return {
        "competency_id": str(competency_id),
        "description": "Calcula el vuelto de una compra",
        "capability_ids": [str(c) for c in capabilities],
        "performance_id": str(performance_id),
    }
