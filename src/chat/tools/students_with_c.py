"""alumnos_con_c: students with C ("en inicio") in at least one competency of a period."""

from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncConnection

from chat.tools import blocks, resolve
from chat.tools.base import Args, Clarify, Param, Tool, ToolOutcome, fetch_rows, rows_for_model
from mawta_schema import api_views as v

RULE = (
    'Un alumno "jalado" o "en inicio" tiene C en al menos una competencia del periodo; se '
    "cuenta por competencia, no por área. Sin nivel no es C. La lista va por sección y "
    "apellido: no ordena alumnos por desempeño."
)


async def run(conn: AsyncConnection, args: Args) -> ToolOutcome:
    try:
        term = resolve.resolve_term(await resolve.terms(conn), args.get("periodo"))
        scope = await resolve.resolve_scope(
            conn, args.get("grado"), args.get("seccion"), args.get("area")
        )
    except Clarify as c:
        return c.outcome()
    if not term["has_levels"]:
        return ToolOutcome(
            result={
                "periodo": term["name"],
                "sin_datos": f"{term['name']} todavía no tiene niveles de logro: los docentes "
                "los registran al cerrar el periodo.",
            }
        )
    L = v.levels.c
    student = (
        L.student_id, L.full_name, L.section_name, L.grade_ordinal, L.section,
        L.paternal_surname, L.maternal_surname,
    )  # fmt: skip
    rows = await fetch_rows(
        conn,
        select(
            *student,
            func.count().label("c_count"),
            func.array_agg(aggregate_order_by(distinct(L.subject_name), L.subject_name)).label(
                "subjects"
            ),
            func.array_agg(
                aggregate_order_by(L.competency_code, L.subject_order, L.competency_order)
            ).label("competencies"),
        )
        .where(L.term_id == term["id"], L.level == "C", *scope.where(v.levels))
        .group_by(*student)
        .order_by(L.grade_ordinal, L.section, L.paternal_surname, L.maternal_surname, L.full_name),
    )
    model_rows: list[dict[str, Any]] = [
        {
            "alumno": r["full_name"],
            "seccion": r["section_name"],
            "cantidad_de_C": r["c_count"],
            "areas": r["subjects"],
            "competencias": r["competencies"],
        }
        for r in rows
    ]
    result: dict[str, Any] = {
        "periodo": term["name"],
        "alcance": scope.describe(),
        "regla": RULE,
        "alumnos_con_C": len(rows),
        "total_de_C": sum(r["c_count"] for r in rows),
        **rows_for_model(model_rows),
    }
    table = blocks.table(
        f"Alumnos con C — {resolve.label(term)}",
        ["Alumno", "Sección", "C", "Áreas"],
        [
            [r["full_name"], r["section_name"], r["c_count"], ", ".join(r["subjects"])]
            for r in rows
        ],  # fmt: skip
        f"{term['name']} · {scope.describe()}. C en al menos una competencia; por sección y "
        "apellido.",
    )
    return ToolOutcome(result=result, blocks=[table] if rows else [])


TOOL = Tool(
    name="alumnos_con_c",
    description=(
        'Lists students with C ("en inicio") in at least one competency in a period, with how '
        "many C they have and in which áreas and competencies. A competency with no level is "
        "never counted as C. Listed by section and surname, never ranked. Defaults to the last "
        'period with levels. Use it for "jalados", "desaprobados", "en inicio" or "con C".'
    ),
    status="Buscando alumnos con C…",
    params={
        "periodo": Param('Period: "actual", "último cerrado", "T-II", "segundo trimestre"…'),
        "grado": Param('Grade as the director said it: "primero", "1ro de secundaria"…'),
        "seccion": Param('Section: "A", "1A", "1ro B"…'),
        "area": Param('Área: "matemática", "MAT", "comu"…'),
    },
    run=run,
)
