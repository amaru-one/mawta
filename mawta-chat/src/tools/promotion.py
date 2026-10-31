"""proyeccion_de_promocion: the promotion rule of the grade, applied to the last period with levels
as if the year ended there."""

from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from tools import blocks, resolve
from tools.base import Args, Clarify, Param, Tool, ToolOutcome, rows_for_model

# Cuadro 5.1.3.A of RVM 048-2024 (p. 8) has one rule for 1.°, 3.° and 4.° de secundaria and
# another, stricter one for 2.° and 5.°, the grades that close a cycle (VI and VII).
MID_CYCLE = (1, 3, 4)
END_OF_CYCLE = (2, 5)
AREAS_TO_REPEAT = 4  # áreas with too many C from which the student would repeat the grade
AREAS_WITH_A = 3  # 2.° and 5.°: áreas with half or more in A or AD needed to be promoted

PROMOTED, RECOVERY, REPEAT = "promovería", "iría a recuperación", "en riesgo de permanecer"
SITUATIONS = (PROMOTED, RECOVERY, REPEAT)

RULE = (
    "Proyección con los niveles de {term}, como si el año cerrara ahí (cuadro 5.1.3.A, RVM "
    "048-2024). Cuenta las competencias con nivel de cada área; sin nivel no es C. La situación "
    "oficial se decide al cerrar el año."
)
RULE_MID = (
    "1.°, 3.° y 4.° de secundaria: promovería con B o más en la mitad o más de las competencias "
    "de cada área; en riesgo de permanecer con C en más de la mitad de las competencias de 4 o "
    "más áreas; si no, iría a recuperación."
)
RULE_END = (
    "2.° y 5.° de secundaria (cierran ciclo): promovería con A o AD en la mitad o más de las "
    "competencias de al menos 3 áreas y B o más en todas las demás, es decir, sin ninguna C; en "
    "riesgo de permanecer con C en la mitad o más de las competencias de 4 o más áreas; si no, "
    "iría a recuperación."
)


@dataclass
class Area:
    name: str
    with_level: int
    a_or_above: int
    b_or_above: int
    c: int


@dataclass
class Projection:
    situation: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)


def names(areas: list[Area]) -> list[str]:
    return [a.name for a in areas]


def project_mid_cycle(areas: list[Area]) -> Projection:
    """1.°, 3.° y 4.°: an área passes with B or above in half or more of its competencies; the
    student repeats with C in more than half of the competencies of 4 or more áreas. With only
    AD/A/B/C, "fewer than half B or above" and "more than half C" are the same áreas."""
    failed = [a for a in areas if 2 * a.b_or_above < a.with_level]
    detail = {"areas_no_aprobadas": names(failed)}
    if not failed:
        return Projection(PROMOTED, "", detail)
    reason = "Menos de la mitad en B o más en: " + ", ".join(names(failed))
    return Projection(REPEAT if len(failed) >= AREAS_TO_REPEAT else RECOVERY, reason, detail)


def project_end_of_cycle(areas: list[Area]) -> Projection:
    """2.° y 5.°: promoted with A or AD in half or more of the competencies of at least 3 áreas
    and B or above in all the rest (no C at all); repeats with C in half or more of the
    competencies of 4 or more áreas; otherwise recovery."""
    half_c = [a for a in areas if a.c > 0 and 2 * a.c >= a.with_level]
    with_c = [a for a in areas if a.c > 0]
    half_a = [a for a in areas if 2 * a.a_or_above >= a.with_level]
    detail = {
        "areas_con_C_en_la_mitad_o_mas": names(half_c),
        "areas_con_alguna_C": names(with_c),
        "areas_con_A_o_AD_en_la_mitad_o_mas": names(half_a),
    }
    if len(half_c) >= AREAS_TO_REPEAT:
        reason = "C en la mitad o más de las competencias de: " + ", ".join(names(half_c))
        return Projection(REPEAT, reason, detail)
    if not with_c and len(half_a) >= AREAS_WITH_A:
        return Projection(PROMOTED, "", detail)
    reasons: list[str] = []
    if with_c:
        reasons.append("C en: " + ", ".join(names(with_c)))
    if len(half_a) < AREAS_WITH_A:
        how_many = {0: "ninguna área", 1: "solo 1 área"}.get(
            len(half_a), f"solo {len(half_a)} áreas"
        )
        reasons.append(f"{how_many} con A o AD en la mitad o más (se piden {AREAS_WITH_A})")
    return Projection(RECOVERY, "; ".join(reasons), detail)


def rule_for(stage: str | None, position: int | None) -> str | None:
    """Which rule of cuadro 5.1.3.A applies, or None when this tool does not know the grade's."""
    if (stage or "").lower() != "secundaria":
        return None
    if position in MID_CYCLE:
        return "mid"
    if position in END_OF_CYCLE:
        return "end"
    return None


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
               count(*) filter (where level_ordinal >= 3) as a_or_above,
               count(*) filter (where level_ordinal >= 2) as b_or_above,
               count(*) filter (where level_ordinal = 1) as c
          from chat_api.levels
         where term_id = %s {where}
         group by student_id, full_name, paternal_surname, maternal_surname, grade, grade_long,
                  grade_ordinal, stage, section, section_name, subject_name, subject_order
         order by subject_order, subject_name
        """,
        [last["id"], *params],
    )
    students: dict[Any, dict[str, Any]] = {}
    no_rule: set[str] = set()
    for r in await cur.fetchall():
        rule = rule_for(r["stage"], resolve.grade_position(r))
        if rule is None:
            no_rule.add(r["grade_long"])
            continue
        s = students.setdefault(r["student_id"], {**r, "rule": rule, "areas": []})
        s["areas"].append(
            Area(r["subject_name"], r["with_level"], r["a_or_above"], r["b_or_above"], r["c"])
        )

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
        project = project_mid_cycle if s["rule"] == "mid" else project_end_of_cycle
        p = project(s["areas"])
        counts[p.situation] += 1
        if p.situation != PROMOTED:
            flagged.append({"alumno": s["full_name"], "seccion": s["section_name"],
                            "situacion_proyectada": p.situation, "motivo": p.reason,
                            **p.detail})  # fmt: skip
    rules = {s["rule"] for s in students.values()}
    result: dict[str, Any] = {
        "con_los_niveles_de": last["name"],
        "alcance": scope.describe(),
        "regla": " ".join(
            [RULE.format(term=last["name"])]
            + ([RULE_MID] if "mid" in rules else [])
            + ([RULE_END] if "end" in rules else [])
        ),
        "es_proyeccion": True,
        "alumnos_por_situacion": counts,
        **rows_for_model(flagged),
    }
    if no_rule:
        result["grados_sin_proyeccion"] = sorted(no_rule)
        result["aviso"] = (
            "La proyección todavía no está disponible para "
            + ", ".join(sorted(no_rule))
            + ": solo se conoce la regla de secundaria."
        )
    table = blocks.table(
        f"Proyección de promoción con los niveles de {resolve.label(last)}",
        ["Alumno", "Sección", "Situación proyectada", "Motivo"],
        [[f["alumno"], f["seccion"], f["situacion_proyectada"], f["motivo"]] for f in flagged],
        f"Proyección, no la situación oficial (se decide al cerrar el año) · {scope.describe()}. "
        f"Promoverían {counts[PROMOTED]}; irían a recuperación {counts[RECOVERY]}; "
        f"en riesgo de permanecer {counts[REPEAT]}.",
    )
    return ToolOutcome(result=result, blocks=[table] if flagged else [])


TOOL = Tool(
    name="proyeccion_de_promocion",
    description=(
        "Projects, for each secondary student, the promotion rule of their grade (RVM 048-2024, "
        "table 5.1.3.A) onto the levels of the last period with levels, as if the year ended "
        "there. 1st, 3rd and 4th grade: promoted with B or above in half or more of each área's "
        "competencies; would repeat with C in more than half of the competencies of 4 or more "
        "áreas. 2nd and 5th grade (end of cycle) are stricter: promoted only with no C at all and "
        "A or AD in half or more of the competencies of at least 3 áreas; would repeat with C in "
        'half or more of the competencies of 4 or more áreas. Otherwise "iría a recuperación". '
        "Each listed student comes with the reason. It is a projection, not the official result. "
        "Use it for who could repeat the grade or go to recovery."
    ),
    status="Proyectando la promoción…",
    params={
        "grado": Param('Grade as the director said it: "primero", "1ro de secundaria"…'),
        "seccion": Param('Section: "A", "1A", "1ro B"…'),
    },
    run=run,
)
