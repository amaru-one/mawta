"""proyeccion_de_promocion: the promotion rule of the grade, applied to the last period with levels
as if the year ended there."""

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from tools import blocks, resolve
from tools.base import Args, Clarify, Param, Tool, ToolOutcome, rows_for_model

# Grades whose rule this tool knows (cuadro 5.1.3.A, RVM 048-2024): 1.°, 3.° y 4.° de
# secundaria promote with B or above in half or more of each área's competencies. 2.° and 5.°
# (end of cycle) have another rule, not projected yet.
GRADES_WITH_RULE = (1, 3, 4)
AT_RISK_AREAS = 4  # áreas not passed from which the student is "en riesgo de permanecer"

RULE = (
    "Proyección con los niveles del último periodo con niveles, como si el año cerrara ahí "
    "(cuadro 5.1.3.A, RVM 048-2024, para 1.°, 3.° y 4.° de secundaria). Un área no está aprobada "
    "cuando menos de la mitad de sus competencias con nivel están en B o más. 1 a 3 áreas no "
    "aprobadas: iría a recuperación; 4 o más: en riesgo de permanecer en el grado. Es una "
    "proyección: la situación oficial se decide al cerrar el año."
)
SITUATIONS = ("promovería", "iría a recuperación", "en riesgo de permanecer")


def situation(areas_not_passed: int) -> str:
    if areas_not_passed == 0:
        return SITUATIONS[0]
    if areas_not_passed < AT_RISK_AREAS:
        return SITUATIONS[1]
    return SITUATIONS[2]


async def run(conn: AsyncConnection[DictRow], args: Args) -> ToolOutcome:
    try:
        last = resolve.resolve_term(await resolve.terms(conn), None)
        scope = await resolve.resolve_scope(conn, args.get("grado"), args.get("seccion"))
    except Clarify as c:
        return c.outcome()
    where, params = scope.where()
    cur = await conn.execute(
        f"""
        select student_id, full_name, paternal_surname, maternal_surname, grade, grade_long,
               grade_ordinal, stage, section, section_name, subject_name, subject_order,
               count(*) as with_level,
               count(*) filter (where level_ordinal >= 2) as b_or_above
          from chat_api.levels
         where term_id = %s {where}
         group by student_id, full_name, paternal_surname, maternal_surname, grade, grade_long,
                  grade_ordinal, stage, section, section_name, subject_name, subject_order
        """,
        [last["id"], *params],
    )
    students: dict[Any, dict[str, Any]] = {}
    no_rule: set[str] = set()
    for r in await cur.fetchall():
        position = resolve.grade_position(r)
        if (r["stage"] or "").lower() != "secundaria" or position not in GRADES_WITH_RULE:
            no_rule.add(r["grade_long"])
            continue
        s = students.setdefault(r["student_id"], {**r, "not_passed": []})
        # Not passed: fewer than half of its competencies with a level are B or above.
        if 2 * r["b_or_above"] < r["with_level"]:
            s["not_passed"].append((r["subject_order"], r["subject_name"]))

    ordered = sorted(
        students.values(),
        key=lambda s: (
            s["grade_ordinal"],
            s["section"],
            s["paternal_surname"],
            s["maternal_surname"] or "",
            s["full_name"],
        ),  # fmt: skip
    )
    counts: dict[str, int] = dict.fromkeys(SITUATIONS, 0)
    flagged: list[dict[str, Any]] = []
    for s in ordered:
        areas = [name for _, name in sorted(s["not_passed"])]
        sit = situation(len(areas))
        counts[sit] += 1
        if areas:
            flagged.append({"alumno": s["full_name"], "seccion": s["section_name"],
                            "areas_no_aprobadas": areas, "situacion_proyectada": sit})  # fmt: skip
    result: dict[str, Any] = {
        "con_los_niveles_de": last["name"],
        "alcance": scope.describe(),
        "regla": RULE,
        "es_proyeccion": True,
        "alumnos_por_situacion": counts,
        **rows_for_model(flagged),
    }
    if no_rule:
        result["grados_sin_proyeccion"] = sorted(no_rule)
        result["aviso"] = (
            "La proyección todavía no está disponible para "
            + ", ".join(sorted(no_rule))
            + ": su regla de promoción es otra."
        )
    table = blocks.table(
        f"Proyección de promoción con los niveles de {resolve.label(last)}",
        ["Alumno", "Sección", "Áreas no aprobadas", "Situación proyectada"],
        [
            [
                f["alumno"],
                f["seccion"],
                ", ".join(f["areas_no_aprobadas"]),
                f["situacion_proyectada"],
            ]
            for f in flagged
        ],  # fmt: skip
        f"Proyección, no la situación oficial (se decide al cerrar el año) · {scope.describe()}. "
        f"Promoverían {counts[SITUATIONS[0]]}; irían a recuperación {counts[SITUATIONS[1]]}; "
        f"en riesgo de permanecer {counts[SITUATIONS[2]]}.",
    )
    return ToolOutcome(result=result, blocks=[table] if flagged else [])


TOOL = Tool(
    name="proyeccion_de_promocion",
    description=(
        "Projects, for each student, the promotion rule of their grade (RVM 048-2024, table "
        "5.1.3.A; 1st, 3rd and 4th grade of secondary) onto the levels of the last period with "
        "levels, as if the year ended there. An área is not passed when fewer than half of its "
        'competencies with a level are B or above. Result per student: "promovería", "iría a '
        'recuperación" (1 to 3 áreas not passed) or "en riesgo de permanecer" (4 or more). It is '
        "a projection, not the official result. Use it for who could repeat the grade or go to "
        "recovery."
    ),
    status="Proyectando la promoción…",
    params={
        "grado": Param('Grade as the director said it: "primero", "1ro de secundaria"…'),
        "seccion": Param('Section: "A", "1A", "1ro B"…'),
    },
    run=run,
)
