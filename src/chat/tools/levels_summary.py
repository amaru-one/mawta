"""resumen_de_niveles: how many levels each achievement level has, and their percentages, by área,
competency or section in one period, with the students apart."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from chat.tools import blocks, levels, resolve
from chat.tools.base import MOSTRAR_BLOQUE, Args, Clarify, Param, Tool, ToolOutcome, shown

RULE = (
    "Nivel de logro = la afirmación vigente del docente por alumno, competencia y periodo. Los "
    "totales cuentan niveles (alumno × competencia), no alumnos: los alumnos van aparte. Los "
    "porcentajes son sobre los niveles registrados; porcentaje_logro = A + AD. Una competencia "
    "sin nivel en el periodo no se cuenta, y nunca es C."
)


async def run(conn: AsyncConnection, args: Args) -> ToolOutcome:
    try:
        all_terms = await resolve.terms(conn)
        term = resolve.resolve_term(all_terms, args.get("periodo"))
        scope = await resolve.resolve_scope(
            conn, args.get("grado"), args.get("seccion"), args.get("area")
        )
    except Clarify as c:
        return c.outcome()
    agrupar_por = args.get("agrupar_por") or levels.default_grouping(scope)
    reported, period_note = resolve.with_levels(all_terms, term)
    if reported is None:
        return ToolOutcome(
            result={
                "periodo": term["name"],
                "sin_datos": f"{term['name']} todavía no tiene niveles de logro: los docentes "
                "los registran al cerrar el periodo.",
            }
        )
    term = reported
    summary = await levels.summarize(conn, term, scope, agrupar_por)
    totals = summary.totals
    result: dict[str, Any] = {
        "periodo": term["name"],
        "alcance": scope.describe(),
        "agrupado_por": agrupar_por,
        "regla": RULE,
        "totales_de_niveles": dict(zip(blocks.LEVELS, totals, strict=True)),
        "porcentajes_totales": levels.percentages(totals),
        "alumnos_evaluados": summary.students,
        "alumnos_con_C": summary.students_with_c,
        "grupos": [{"grupo": g.name, **g.as_result()} for g in summary.groups],
    }
    if period_note:
        result["aviso_periodo"] = period_note
    if summary.without_levels:
        result["competencias_sin_nivel"] = summary.without_levels
    note = (
        f"{term['name']} · {scope.describe()}. Cuenta niveles de logro (alumno × competencia): "
        f"{summary.students} alumnos evaluados, {summary.students_with_c} con alguna C."
        + (
            " Sin nivel en este periodo: "
            + ", ".join(c.split(" · ")[0] for c in summary.without_levels)
            + "."
            if summary.without_levels
            else ""
        )
    )
    bars = (
        blocks.stacked_bars(
            f"Niveles de logro por {levels.GROUPING_LABEL[agrupar_por]} — {resolve.label(term)}",
            [(g.name, g.counts) for g in summary.groups],
            note,
        )
        if summary.groups
        else None
    )
    return ToolOutcome(result=result, blocks=shown(args, bars))


TOOL = Tool(
    name="resumen_de_niveles",
    description=(
        "Counts achievement levels (one per student and competency: AD, A, B or C) in one "
        "period, grouped by área, by competency (of one área, or all) or by section. For every "
        "group and for the total it gives the counts, the percentage of each level "
        "(porcentaje_AD, porcentaje_A, porcentaje_B, porcentaje_C) and porcentaje_logro (A + AD), "
        "plus how many students that is: alumnos (evaluated) and alumnos_con_C. Level counts are "
        "not students (168 levels in Matemática are 56 students × 3 competencies): copy both as "
        'the tool gives them. A competency with no level is "sin nivel", never C, and the result '
        "lists those. Defaults to the last period with levels, because levels are asserted when "
        "a period closes. Use it for how a grade, a section or an área is doing, to compare "
        "groups within a period, or as the first step before looking into the students of a "
        "group (alumnos_con_c, riesgo_por_competencia). To see how something changed between "
        "periods, use comparar_periodos."
    ),
    status="Contando los niveles de logro…",
    params={
        "periodo": Param(
            'Period, only when the director named one ("actual", "último cerrado" or its name). '
            "Empty = the last period with levels; do not fill it otherwise."
        ),
        "grado": Param(resolve.GRADO_HINT),
        "seccion": Param(resolve.SECCION_HINT),
        "area": Param(
            "Área, only when the director named one or a previous result pointed to it. Empty = "
            "every área."
        ),
        "agrupar_por": Param(
            'One group per "area", per "competencia" or per "seccion". Default: per área, or per '
            "competency when an área is given.",
            enum=levels.GROUPING_NAMES,
        ),
        "mostrar_bloque": MOSTRAR_BLOQUE,
    },
    run=run,
    topic="niveles de logro (AD, A, B, C) y sus porcentajes por área, competencia o sección",
)
