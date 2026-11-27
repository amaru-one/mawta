"""comparar_periodos: how the achievement levels of a scope changed from one period to another,
with every difference already computed (in percentage points and in students), so the model
reports real changes without doing arithmetic of its own (D007)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from chat.tools import blocks, levels, resolve
from chat.tools.base import MOSTRAR_BLOQUE, Args, Clarify, Param, Tool, ToolOutcome, shown

RULE = (
    "Compara los niveles de logro vigentes registrados en cada periodo, en el mismo alcance. Los "
    "porcentajes son sobre los niveles de cada periodo (alumno × competencia); porcentaje_logro "
    "= A + AD. variacion = periodo final − periodo inicial: en puntos porcentuales para los "
    "porcentajes y en alumnos para los conteos de alumnos. La matrícula y las competencias "
    "trabajadas pueden cambiar de un periodo a otro. Sin nivel no se cuenta y nunca es C."
)


def _side(group: levels.Group | None) -> dict[str, Any] | None:
    return group.as_result() if group is not None else None


def _total(group: levels.Group) -> dict[str, Any]:
    """A period's total: its students are the students evaluated in the whole scope."""
    out = group.as_result()
    out["alumnos_evaluados"] = out.pop("alumnos")
    return out


def variation(before: levels.Group, after: levels.Group) -> dict[str, Any]:
    """after − before. Percentages: the difference of the rounded figures the result states, so
    it matches what the model reads; counts of students: exact."""
    p_before, p_after = levels.percentages(before.counts), levels.percentages(after.counts)
    return {
        **{k: round(p_after[k] - p_before[k], 1) for k in levels.PERCENTAGES},
        "alumnos_con_C": after.students_with_c - before.students_with_c,
        "alumnos_evaluados": after.students - before.students,
    }


def _signed(value: float) -> str:
    """ "+3.2", "-1.0", "0.0": a variation as the table shows it."""
    value = round(value, 1)
    return f"{value:+.1f}" if value else "0.0"


def _row(name: str, before: levels.Group | None, after: levels.Group | None) -> list[Any]:
    """One row of the comparison table; a group missing in a period has empty cells there."""
    pb = levels.percentages(before.counts) if before else {}
    pa = levels.percentages(after.counts) if after else {}
    change = variation(before, after) if before and after else {}
    return [
        name,
        pb.get("porcentaje_logro"),
        pa.get("porcentaje_logro"),
        _signed(change["porcentaje_logro"]) if change else None,
        pb.get("porcentaje_C"),
        pa.get("porcentaje_C"),
        _signed(change["porcentaje_C"]) if change else None,
        before.students_with_c if before else None,
        after.students_with_c if after else None,
    ]


def pick_terms(
    all_terms: list[dict[str, Any]], first_text: str | None, second_text: str | None
) -> tuple[dict[str, Any], dict[str, Any]] | str:
    """The two periods to compare, in order, or why there is nothing to compare. Without names:
    the last two periods with levels. With one name: that period and the last one with levels
    (or the one before it, when the named one is the last)."""
    with_levels = [t for t in all_terms if t["has_levels"]]
    if not with_levels:
        return (
            "Ningún periodo del año activo tiene todavía niveles de logro: no hay nada que "
            "comparar."
        )
    if len(with_levels) < 2:
        return (
            f"Solo {with_levels[0]['name']} tiene niveles de logro en el año activo: hacen falta "
            "dos periodos con niveles para comparar."
        )
    named = [resolve.resolve_term(all_terms, text) if text else None
             for text in (first_text, second_text)]  # fmt: skip
    for term in named:
        if term is not None and not term["has_levels"]:
            return (
                f"{term['name']} todavía no tiene niveles de logro (los docentes los registran al "
                "cerrar el periodo), así que no se puede comparar. Periodos con niveles: "
                + ", ".join(t["name"] for t in with_levels)
                + "."
            )
    first, second = named
    if first is None and second is None:
        first, second = with_levels[-2], with_levels[-1]
    elif first is None or second is None:
        given = first or second
        assert given is not None
        other = with_levels[-1] if given["id"] != with_levels[-1]["id"] else with_levels[-2]
        first, second = given, other
    if first["id"] == second["id"]:
        raise Clarify(
            f"Para comparar hacen falta dos periodos distintos (los dos son {first['name']}).",
            [t["name"] for t in with_levels],
        )
    return (first, second) if first["sequence"] < second["sequence"] else (second, first)


async def run(conn: AsyncConnection, args: Args) -> ToolOutcome:
    try:
        all_terms = await resolve.terms(conn)
        picked = pick_terms(all_terms, args.get("periodo_inicial"), args.get("periodo_final"))
        scope = await resolve.resolve_scope(
            conn, args.get("grado"), args.get("seccion"), args.get("area")
        )
    except Clarify as c:
        return c.outcome()
    if isinstance(picked, str):
        return ToolOutcome(result={"sin_datos": picked})
    first, second = picked
    agrupar_por = args.get("agrupar_por") or levels.default_grouping(scope)
    before = await levels.summarize(conn, first, scope, agrupar_por)
    after = await levels.summarize(conn, second, scope, agrupar_por)

    names = [g.name for g in before.groups]
    names += [g.name for g in after.groups if g.name not in names]
    groups: list[dict[str, Any]] = []
    only_one: list[str] = []
    for name in names:
        b, a = before.group(name), after.group(name)
        row: dict[str, Any] = {"grupo": name, "inicial": _side(b), "final": _side(a)}
        if b is not None and a is not None:
            row["variacion"] = variation(b, a)
        else:
            only_one.append(name)
        groups.append(row)
    total_before, total_after = before.total(), after.total()
    result: dict[str, Any] = {
        "periodo_inicial": first["name"],
        "periodo_final": second["name"],
        "alcance": scope.describe(),
        "agrupado_por": agrupar_por,
        "regla": RULE,
        "totales": {
            "inicial": _total(total_before),
            "final": _total(total_after),
            "variacion": variation(total_before, total_after),
        },
        "grupos": groups,
    }
    if not before.groups or not after.groups:
        empty = first["name"] if not before.groups else second["name"]
        result["aviso"] = f"{empty} no tiene niveles de logro en este alcance."
    if only_one:
        result["solo_en_un_periodo"] = only_one
    without = {
        t["name"]: s.without_levels
        for t, s in ((first, before), (second, after))
        if s.without_levels
    }
    if without:
        result["competencias_sin_nivel"] = without

    a, b = resolve.label(first), resolve.label(second)

    table = (
        blocks.table(
            f"Comparación {a} → {b} por {levels.GROUPING_LABEL[agrupar_por]}",
            [
                levels.GROUPING_LABEL[agrupar_por].capitalize(),
                f"% A+AD {a}",
                f"% A+AD {b}",
                "Var. A+AD",
                f"% C {a}",
                f"% C {b}",
                "Var. C",
                f"Alumnos con C {a}",
                f"Alumnos con C {b}",
            ],
            [_row(n, before.group(n), after.group(n)) for n in names]
            + [_row("Total", total_before, total_after)],
            f"{first['name']} → {second['name']} · {scope.describe()}. Porcentajes sobre los "
            "niveles de cada periodo (alumno × competencia); variación en puntos porcentuales. "
            "Sin nivel no se cuenta.",
        )
        if names
        else None
    )
    return ToolOutcome(result=result, blocks=shown(args, table))


TOOL = Tool(
    name="comparar_periodos",
    description=(
        "Compares the achievement levels of two periods in the same scope (the whole school, a "
        "grade, a section and/or an área), grouped by área, competency or section. For each "
        "group and for the total it gives both periods (counts, porcentaje_AD/A/B/C, "
        "porcentaje_logro = A + AD, alumnos, alumnos_con_C) and their variacion (final − "
        "initial): in percentage points for the percentages, in students for alumnos_con_C and "
        "alumnos_evaluados. Copy the variations as given; never subtract figures yourself. "
        "Defaults to the last two periods with levels; with one period named, compares it with "
        "the last one with levels. A period without levels cannot be compared and the tool says "
        "so. Use it for what improved or worsened, which áreas or sections went up or down, or "
        "how a group evolved."
    ),
    status="Comparando periodos…",
    params={
        "periodo_inicial": Param(
            "The earlier period, only when the director named it (its name or short name). "
            "Empty = the second-to-last period with levels."
        ),
        "periodo_final": Param(
            "The later period, only when the director named it. Empty = the last period with "
            "levels."
        ),
        "grado": Param(resolve.GRADO_HINT),
        "seccion": Param(resolve.SECCION_HINT),
        "area": Param(
            "Área, only when the director named one or a previous result pointed to it. Empty = "
            "every área."
        ),
        "agrupar_por": Param(
            'One row per "area", per "competencia" or per "seccion". Default: per área, or per '
            "competency when an área is given.",
            enum=levels.GROUPING_NAMES,
        ),
        "mostrar_bloque": MOSTRAR_BLOQUE,
    },
    run=run,
    topic="cómo cambiaron los niveles de logro entre dos periodos (variaciones exactas)",
)
