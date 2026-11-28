"""What resumen_de_niveles and comparar_periodos share: the count of achievement levels of one
period in a scope, grouped by área, competency or section, with the students apart and every
percentage already computed, so the model copies figures instead of working them out."""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from chat.tools import blocks, resolve
from chat.tools.base import fetch_rows
from mawta_schema import api_views as v

GROUPINGS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # agrupar_por: (columns of chat_api.levels that identify a group, order)
    "area": (("subject_code", "subject_name", "subject_order"), ("subject_order", "subject_code")),
    "competencia": (
        ("subject_code", "subject_order", "competency_code", "competency_name", "competency_order"),
        ("subject_order", "competency_order", "competency_code"),
    ),
    "seccion": (("grade_ordinal", "section", "section_name"), ("grade_ordinal", "section")),
}
GROUPING_NAMES = tuple(GROUPINGS)
GROUPING_LABEL = {"area": "área", "competencia": "competencia", "seccion": "sección"}
PERCENTAGES = ("porcentaje_AD", "porcentaje_A", "porcentaje_B", "porcentaje_C", "porcentaje_logro")


def group_label(agrupar_por: str, row: dict[str, Any]) -> str:
    if agrupar_por == "area":
        return row["subject_name"]
    if agrupar_por == "competencia":
        return f"{row['competency_code']} · {row['competency_name']}"
    return row["section_name"]


def default_grouping(scope: resolve.Scope) -> str:
    """Per competency when the scope is one área, per área otherwise."""
    return "competencia" if scope.area else "area"


def percent(part: int, whole: int) -> float:
    """One decimal, 0 when there is nothing to divide."""
    return round(100 * part / whole, 1) if whole else 0.0


def percentages(counts: list[int]) -> dict[str, float]:
    """The share of each level among the levels counted (AD, A, B, C) and porcentaje_logro, the
    share in A or AD (logro esperado or destacado)."""
    total = sum(counts)
    ad, a, b, c = counts
    return {
        "porcentaje_AD": percent(ad, total),
        "porcentaje_A": percent(a, total),
        "porcentaje_B": percent(b, total),
        "porcentaje_C": percent(c, total),
        "porcentaje_logro": percent(ad + a, total),
    }


@dataclass
class Group:
    name: str
    counts: list[int]  # AD, A, B, C
    students: int = 0
    students_with_c: int = 0

    def as_result(self) -> dict[str, Any]:
        return {
            **dict(zip(blocks.LEVELS, self.counts, strict=True)),
            "total_niveles": sum(self.counts),
            **percentages(self.counts),
            "alumnos": self.students,
            "alumnos_con_C": self.students_with_c,
        }


@dataclass
class Summary:
    """One period's levels in a scope. groups keep the school's order (área, competency or
    grade and section)."""

    term: dict[str, Any]
    agrupar_por: str
    groups: list[Group] = field(default_factory=list)
    students: int = 0
    students_with_c: int = 0
    without_levels: list[str] = field(default_factory=list)  # "MAT-C2 · …"

    @property
    def totals(self) -> list[int]:
        return [sum(g.counts[i] for g in self.groups) for i in range(4)]

    def total(self) -> Group:
        return Group("Total", self.totals, self.students, self.students_with_c)

    def group(self, name: str) -> Group | None:
        return next((g for g in self.groups if g.name == name), None)


async def summarize(
    conn: AsyncConnection, term: dict[str, Any], scope: resolve.Scope, agrupar_por: str
) -> Summary:
    """Counts the live levels of `term` in `scope`, per group, and the distinct students
    evaluated and with at least one C, per group and overall. Also lists the competencies of the
    scope with no level at all in the term: worth saying, and never a C."""
    names, order = GROUPINGS[agrupar_por]
    L = v.levels.c
    in_scope = [L.term_id == term["id"], *scope.where(v.levels)]
    cols = [L[n] for n in names]
    summary = Summary(term, agrupar_por)
    by_name: dict[str, Group] = {}
    for r in await fetch_rows(
        conn,
        select(*cols, L.level, func.count().label("n"))
        .where(*in_scope)
        .group_by(*cols, L.level)
        .order_by(*(L[n] for n in order)),
    ):
        name = group_label(agrupar_por, r)
        if name not in by_name:
            by_name[name] = Group(name, [0, 0, 0, 0])
            summary.groups.append(by_name[name])
        by_name[name].counts[blocks.LEVELS.index(r["level"])] += r["n"]
    # Students, not levels: the model copies these instead of taking a total of levels for
    # students.
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
        group = by_name.get(group_label(agrupar_por, r))
        if group is not None:
            group.students, group.students_with_c = r["alumnos"], r["con_c"]
    overall = await fetch_rows(
        conn,
        select(
            func.count(distinct(L.student_id)).label("alumnos"),
            func.count(distinct(L.student_id)).filter(L.level == "C").label("con_c"),
        ).where(*in_scope),
    )
    summary.students, summary.students_with_c = overall[0]["alumnos"], overall[0]["con_c"]

    c = v.competencies.c
    area_filter = [c.subject_code == scope.area["subject_code"]] if scope.area else []
    all_competencies = await fetch_rows(
        conn,
        select(c.code, c.name).where(*area_filter).order_by(c.subject_order, c.sort_order),
    )
    with_levels = set(
        (await conn.execute(select(L.competency_code).distinct().where(*in_scope))).scalars()
    )
    summary.without_levels = [
        f"{r['code']} · {r['name']}" for r in all_competencies if r["code"] not in with_levels
    ]
    return summary
