"""datos_del_colegio: how the school is organised this year."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from chat.tools import blocks, resolve
from chat.tools.base import Args, Tool, ToolOutcome, fetch_rows
from mawta_schema import api_views as v

SHIFTS = {"manana": "Mañana", "tarde": "Tarde", "noche": "Noche", "completo": "Completo"}
TERM_STATUS = {"planned": "por empezar", "active": "en curso", "closed": "cerrado",
               "archived": "archivado"}  # fmt: skip


async def run(conn: AsyncConnection, _args: Args) -> ToolOutcome:
    school = (await conn.execute(select(v.school.c.name))).mappings().first()
    all_terms = await resolve.terms(conn)
    all_sections = await resolve.sections(conn)
    k = v.classes.c
    classes = await fetch_rows(
        conn,
        select(k.section_id, k.subject_name, k.subject_code, k.teacher, k.tutor)
        .where(k.academic_year_status == "active")
        .order_by(k.grade_ordinal, k.section, k.subject_code),
    )
    s = v.students.c
    counts = {
        r["section_id"]: r["students"]
        for r in await fetch_rows(
            conn,
            select(s.section_id, func.count().label("students"))
            .where(s.academic_year_status == "active", s.left_on.is_(None))
            .group_by(s.section_id),
        )
    }
    tutors: dict[Any, str | None] = {}
    for c in classes:
        tutors.setdefault(c["section_id"], c["tutor"])

    year = all_terms[0]["academic_year"] if all_terms else None
    sections_out = [
        {
            "grado": s["grade_long"],
            "seccion": s["name"],
            "turno": SHIFTS.get(s["shift"], s["shift"]),
            "tutor": tutors.get(s["id"]),
            "alumnos": counts.get(s["id"], 0),
        }
        for s in all_sections
    ]
    result: dict[str, Any] = {
        "colegio": school["name"] if school else None,
        "anio_escolar": year,
        "periodos": [
            {
                "nombre": t["name"],
                "abreviatura": t["short_name"],
                "inicio": t["starts_on"].isoformat(),
                "fin": t["ends_on"].isoformat(),
                "estado": TERM_STATUS.get(t["status"], t["status"]),
                "es_el_actual": t["is_current"],
                "tiene_niveles_de_logro": t["has_levels"],
            }
            for t in all_terms
        ],
        "secciones": sections_out,
        "docentes_por_clase": [
            {
                "seccion": next(
                    (s["name"] for s in all_sections if s["id"] == c["section_id"]), None
                ),  # fmt: skip
                "area": c["subject_name"],
                "docente": c["teacher"],
            }
            for c in classes
        ],
    }
    table = blocks.table(
        f"Secciones del colegio ({year})" if year else "Secciones del colegio",
        ["Grado", "Sección", "Turno", "Tutor", "Alumnos"],
        [[s["grado"], s["seccion"], s["turno"], s["tutor"], s["alumnos"]] for s in sections_out],
        "Fuente: secciones, tutores y matrículas vigentes registradas en Mawta.",
    )
    return ToolOutcome(result=result, blocks=[table] if sections_out else [])


TOOL = Tool(
    name="datos_del_colegio",
    description=(
        "Returns the school's structure for the active academic year: its periods with dates "
        "and status (which one is current, and which already have achievement levels), its "
        "grades and sections with their tutor, shift and number of students, and the teacher "
        "of each class. Use it for questions about how the school is organised, what period "
        "it is, or who teaches or tutors a group. Takes no parameters."
    ),
    status="Consultando los datos del colegio…",
    params={},
    run=run,
)
