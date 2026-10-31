"""riesgo_por_competencia: students with C in the same competency in consecutive periods."""

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from tools import blocks, resolve
from tools.base import Args, Clarify, Param, Tool, ToolOutcome, rows_for_model

RULE = (
    "En riesgo = C en la misma competencia en periodos seguidos, terminando en el último periodo "
    "con niveles. La racha cuenta periodos consecutivos; un periodo sin nivel en esa competencia "
    "la corta."
)


async def run(conn: AsyncConnection[DictRow], args: Args) -> ToolOutcome:
    try:
        all_terms = await resolve.terms(conn)
        last = resolve.resolve_term(all_terms, None)
        scope = await resolve.resolve_scope(
            conn, args.get("grado"), args.get("seccion"), args.get("area")
        )
    except Clarify as c:
        return c.outcome()
    minimum = max(2, int(args.get("minimo") or 2))
    where, params = scope.where()
    # Every C of the year up to the last period with levels; the streak is counted below.
    cur = await conn.execute(
        f"""
        select student_id, full_name, paternal_surname, maternal_surname, grade_ordinal, section,
               section_name, subject_order, competency_code, competency_name, competency_order,
               term_sequence
          from chat_api.levels
         where academic_year_status = 'active' and level = 'C' and term_sequence <= %s {where}
        """,
        [last["sequence"], *params],
    )
    c_terms: dict[tuple[Any, str], set[int]] = {}
    info: dict[tuple[Any, str], dict[str, Any]] = {}
    for r in await cur.fetchall():
        key = (r["student_id"], r["competency_code"])
        c_terms.setdefault(key, set()).add(r["term_sequence"])
        if r["term_sequence"] == last["sequence"]:
            info[key] = r  # the section of the latest period
    names = {t["sequence"]: resolve.label(t) for t in all_terms}

    found: list[dict[str, Any]] = []
    for key, r in info.items():
        streak = 0
        while last["sequence"] - streak in c_terms[key]:
            streak += 1
        if streak >= minimum:
            seqs = range(last["sequence"] - streak + 1, last["sequence"] + 1)
            found.append({**r, "streak": streak, "periods": [names[s] for s in seqs]})
    found.sort(
        key=lambda r: (
            r["grade_ordinal"],
            r["section"],
            r["paternal_surname"],
            r["maternal_surname"] or "",
            r["full_name"],
            r["subject_order"],
            r["competency_order"],
        )  # fmt: skip
    )
    model_rows = [
        {
            "alumno": r["full_name"],
            "seccion": r["section_name"],
            "competencia": f"{r['competency_code']} · {r['competency_name']}",
            "racha": r["streak"],
            "periodos": r["periods"],
        }
        for r in found
    ]
    by_competency: dict[str, int] = {}
    for r in found:
        by_competency[r["competency_code"]] = by_competency.get(r["competency_code"], 0) + 1
    result: dict[str, Any] = {
        "hasta_el_periodo": last["name"],
        "alcance": scope.describe(),
        "regla": RULE,
        "racha_minima": minimum,
        "alumnos_en_riesgo": len({r["student_id"] for r in found}),
        "casos_por_competencia": by_competency,
        **rows_for_model(model_rows),
    }
    table = blocks.table(
        f"Alumnos en riesgo por competencia — hasta {resolve.label(last)}",
        ["Alumno", "Sección", "Competencia", "Racha", "Periodos"],
        [
            [
                r["full_name"],
                r["section_name"],
                f"{r['competency_code']} · {r['competency_name']}",
                r["streak"],
                ", ".join(r["periods"]),
            ]
            for r in found
        ],  # fmt: skip
        f"C en la misma competencia en {minimum} o más periodos seguidos, hasta {last['name']} · "
        f"{scope.describe()}.",
    )
    return ToolOutcome(result=result, blocks=[table] if found else [])


TOOL = Tool(
    name="riesgo_por_competencia",
    description=(
        "Lists students at risk in a competency: those with C in the same competency in two or "
        "more consecutive periods, ending in the last period with levels. The streak counts "
        "consecutive periods; a period with no level in that competency breaks it. Use it for "
        '"en riesgo", "C seguidas" or "dos trimestres en C".'
    ),
    status="Buscando rachas de C…",
    params={
        "grado": Param('Grade as the director said it: "primero", "1ro de secundaria"…'),
        "seccion": Param('Section: "A", "1A", "1ro B"…'),
        "area": Param('Área: "matemática", "MAT", "comu"…'),
        "minimo": Param("Shortest streak to list, in periods (default 2).", kind="integer"),
    },
    run=run,
)
