"""historial_del_alumno: one student's level in every competency, period by period."""

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from tools import blocks, resolve
from tools.base import Args, Clarify, Param, Tool, ToolOutcome

RULE = (
    "Niveles de logro vigentes del año, por competencia y periodo. Una celda vacía es sin nivel "
    "(la competencia no se trabajó o el alumno aún no estaba), nunca C."
)


async def run(conn: AsyncConnection[DictRow], args: Args) -> ToolOutcome:
    try:
        if not args.get("alumno"):
            raise Clarify("¿De qué alumno? Escribe su nombre o sus apellidos.", [])
        student = await resolve.resolve_student(conn, args["alumno"])
        all_terms = await resolve.terms(conn)
    except Clarify as c:
        return c.outcome()
    # The áreas of the student's section, with every competency, so the empty cells show.
    cur = await conn.execute(
        """
        select c.subject_code, c.subject_name, c.subject_order, c.code, c.name, c.sort_order
          from chat_api.competencies c
         where c.subject_code in (select subject_code from chat_api.classes where section_id = %s)
         order by c.subject_order, c.sort_order, c.code
        """,
        [student["section_id"]],
    )
    competencies = await cur.fetchall()
    cur = await conn.execute(
        """
        select competency_code, term_sequence, level
          from chat_api.levels
         where student_id = %s and academic_year_status = 'active'
        """,
        [student["student_id"]],
    )
    level_of = {
        (r["competency_code"], r["term_sequence"]): r["level"] for r in await cur.fetchall()
    }

    columns = [resolve.label(t) for t in all_terms]
    rows: list[tuple[str, str, list[str | None]]] = []
    model_rows: list[dict[str, Any]] = []
    c_per_term = dict.fromkeys(columns, 0)
    for c in competencies:
        cells = [level_of.get((c["code"], t["sequence"])) for t in all_terms]
        rows.append((c["subject_name"], f"{c['code']} · {c['name']}", cells))
        model_rows.append(
            {
                "area": c["subject_name"],
                "competencia": f"{c['code']} · {c['name']}",
                **{col: (cell or "sin nivel") for col, cell in zip(columns, cells, strict=True)},
            }
        )
        for col, cell in zip(columns, cells, strict=True):
            if cell == "C":
                c_per_term[col] += 1
    without_levels = [t["name"] for t in all_terms if not t["has_levels"]]
    result: dict[str, Any] = {
        "alumno": student["full_name"],
        "seccion": student["section_name"],
        "grado": student["grade_long"],
        "matriculado_desde": student["joined_on"].isoformat(),
        "regla": RULE,
        "cantidad_de_C_por_periodo": c_per_term,
        "competencias": model_rows,
    }
    if student["left_on"] is not None:
        result["retirado_de_la_seccion_el"] = student["left_on"].isoformat()
    if without_levels:
        result["periodos_sin_niveles_aun"] = without_levels
    matrix = blocks.matrix(
        f"Niveles de logro de {student['full_name']} ({student['section_name']})",
        columns,
        rows,
        "Niveles vigentes por competencia y periodo; vacío = sin nivel, nunca C."
        + (f" {', '.join(without_levels)}: todavía sin niveles." if without_levels else ""),
    )
    return ToolOutcome(result=result, blocks=[matrix] if rows else [])


TOOL = Tool(
    name="historial_del_alumno",
    description=(
        "Returns one student's achievement level in every competency of their section's áreas, "
        'for each period of the active year; an empty cell is "sin nivel", never C. Use it for '
        "questions about one student. Parameter: alumno, the student's name as the director wrote "
        "it; if several students match, the tool returns the options to choose from."
    ),
    status="Revisando el historial del alumno…",
    params={"alumno": Param('The student\'s name and/or surnames: "Brenda Quispe".')},
    run=run,
)
