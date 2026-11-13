"""resumen_de_niveles: how many students reached each achievement level, by área, competency or
section."""

from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from chat.tools import blocks, resolve
from chat.tools.base import Args, Clarify, Param, Tool, ToolOutcome, fetch_rows
from mawta_schema import api_views as v

RULE = (
    "Nivel de logro = la afirmación vigente del docente por alumno, competencia y periodo. Los "
    "totales cuentan niveles (alumno × competencia), no alumnos: los alumnos van aparte. Una "
    "competencia sin nivel en el periodo no se cuenta, y nunca es C."
)

GROUPINGS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # agrupar_por: (columns of chat_api.levels that identify a group, order)
    "area": (("subject_code", "subject_name", "subject_order"), ("subject_order", "subject_code")),
    "competencia": (
        ("subject_code", "subject_order", "competency_code", "competency_name", "competency_order"),
        ("subject_order", "competency_order", "competency_code"),
    ),
    "seccion": (("grade_ordinal", "section", "section_name"), ("grade_ordinal", "section")),
}


def group_label(agrupar_por: str, row: dict[str, Any]) -> str:
    if agrupar_por == "area":
        return row["subject_name"]
    if agrupar_por == "competencia":
        return f"{row['competency_code']} · {row['competency_name']}"
    return row["section_name"]


async def run(conn: AsyncConnection, args: Args) -> ToolOutcome:
    try:
        term = resolve.resolve_term(await resolve.terms(conn), args.get("periodo"))
        scope = await resolve.resolve_scope(
            conn, args.get("grado"), args.get("seccion"), args.get("area")
        )
    except Clarify as c:
        return c.outcome()
    agrupar_por = args.get("agrupar_por") or ("competencia" if scope.area else "area")
    if not term["has_levels"]:
        return ToolOutcome(
            result={
                "periodo": term["name"],
                "sin_datos": f"{term['name']} todavía no tiene niveles de logro: los docentes "
                "los registran al cerrar el periodo.",
            }
        )
    names, order = GROUPINGS[agrupar_por]
    L = v.levels.c
    in_scope = [L.term_id == term["id"], *scope.where(v.levels)]
    cols = [L[n] for n in names]
    counts: dict[str, list[int]] = {}
    for r in await fetch_rows(
        conn,
        select(*cols, L.level, func.count().label("n"))
        .where(*in_scope)
        .group_by(*cols, L.level)
        .order_by(*(L[n] for n in order)),
    ):
        bucket = counts.setdefault(group_label(agrupar_por, r), [0, 0, 0, 0])
        bucket[blocks.LEVELS.index(r["level"])] += r["n"]
    # Students, not levels: how many were evaluated and how many have at least one C, per group
    # and overall. The model copies these instead of taking a total of levels for students.
    students_of: dict[str, tuple[int, int]] = {}
    for r in await fetch_rows(
        conn,
        select(
            *cols,
            func.count(distinct(L.student_id)).label("alumnos"),
            func.count(distinct(L.student_id)).filter(L.level == "C").label("con_c"),
        )
        .where(*in_scope)
        .group_by(*cols),
    ):
        students_of[group_label(agrupar_por, r)] = (r["alumnos"], r["con_c"])
    overall = await fetch_rows(
        conn,
        select(
            func.count(distinct(L.student_id)).label("alumnos"),
            func.count(distinct(L.student_id)).filter(L.level == "C").label("con_c"),
        ).where(*in_scope),
    )
    students, students_with_c = overall[0]["alumnos"], overall[0]["con_c"]

    # Competencies of the scope with no level at all in the term: worth saying, never a C.
    c = v.competencies.c
    area_filter = [c.subject_code == scope.area["subject_code"]] if scope.area else []
    all_competencies = await fetch_rows(
        conn,
        select(c.code, c.name).where(*area_filter).order_by(c.subject_order, c.sort_order),
    )
    with_levels = set(
        (await conn.execute(select(L.competency_code).distinct().where(*in_scope))).scalars()
    )
    without = [f"{c['code']} · {c['name']}" for c in all_competencies
               if c["code"] not in with_levels]  # fmt: skip

    groups = [
        {
            "grupo": name,
            **{lv: values[i] for i, lv in enumerate(blocks.LEVELS)},
            "total_niveles": sum(values),
            "porcentaje_C": round(100 * values[3] / sum(values)) if sum(values) else 0,
            "alumnos": students_of.get(name, (0, 0))[0],
            "alumnos_con_C": students_of.get(name, (0, 0))[1],
        }
        for name, values in counts.items()
    ]
    totals = [sum(v[i] for v in counts.values()) for i in range(4)]
    result: dict[str, Any] = {
        "periodo": term["name"],
        "alcance": scope.describe(),
        "agrupado_por": agrupar_por,
        "regla": RULE,
        "totales_de_niveles": dict(zip(blocks.LEVELS, totals, strict=True)),
        "alumnos_evaluados": students,
        "alumnos_con_C": students_with_c,
        "grupos": groups,
    }
    if without:
        result["competencias_sin_nivel"] = without
    note = (
        f"{term['name']} · {scope.describe()}. Cuenta niveles de logro (alumno × competencia): "
        f"{students} alumnos evaluados, {students_with_c} con alguna C."
        + (
            f" Sin nivel en este periodo: {', '.join(c.split(' · ')[0] for c in without)}."
            if without
            else ""
        )
    )
    bars = blocks.stacked_bars(
        f"Niveles de logro por {'área' if agrupar_por == 'area' else agrupar_por} — {label(term)}",
        list(counts.items()),
        note,
    )
    return ToolOutcome(result=result, blocks=[bars] if counts else [])


def label(term: dict[str, Any]) -> str:
    return resolve.label(term)


TOOL = Tool(
    name="resumen_de_niveles",
    description=(
        "Counts achievement levels (one per student and competency: AD, A, B or C) in a period, "
        "grouped by área, by competency (of one área, or all) or by section, and says how many "
        "students that is: alumnos_evaluados and alumnos_con_C, overall and per group. Level "
        "counts are not students (168 levels in Matemática are 56 students × 3 competencies): "
        "copy both as the tool gives them. A level is the teacher's official assertion per "
        'competency and period; a competency with no level is "sin nivel", never C, and the '
        "result lists those. Defaults to the last period with levels, because levels are "
        "asserted when a period closes. Use it for how a grade, a section or an área is doing, "
        "or to compare sections."
    ),
    status="Contando los niveles de logro…",
    params={
        "periodo": Param(
            'Period, only when the director named one ("actual", "último cerrado" or its name). '
            "Empty = the last period with levels; do not fill it otherwise."
        ),
        "grado": Param(
            "Grade, only when the director named one. Empty = the whole school; do not fill it "
            "otherwise."
        ),
        "seccion": Param(
            "Section, only when the director named one. Empty = every section; do not fill it "
            "otherwise."
        ),
        "area": Param(
            "Área, only when the director named one. Empty = every área; do not fill it otherwise."
        ),
        "agrupar_por": Param(
            'One bar per "area", per "competencia" or per "seccion". Default: per área, or per '
            "competency when an área is given.",
            enum=("area", "competencia", "seccion"),
        ),
    },
    run=run,
)
