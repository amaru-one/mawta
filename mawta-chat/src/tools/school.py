"""datos_del_colegio: how the school is organised this year."""

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from tools import blocks, resolve
from tools.base import Args, Tool, ToolOutcome

SHIFTS = {"manana": "Mañana", "tarde": "Tarde", "noche": "Noche", "completo": "Completo"}
TERM_STATUS = {"planned": "por empezar", "active": "en curso", "closed": "cerrado",
               "archived": "archivado"}  # fmt: skip


async def run(conn: AsyncConnection[DictRow], _args: Args) -> ToolOutcome:
    cur = await conn.execute("select name from chat_api.school")
    school = await cur.fetchone()
    all_terms = await resolve.terms(conn)
    all_sections = await resolve.sections(conn)
    cur = await conn.execute(
        """
        select section_id, subject_name, subject_code, teacher, tutor
          from chat_api.classes
         where academic_year_status = 'active'
         order by grade_ordinal, section, subject_code
        """
    )
    classes = await cur.fetchall()
    cur = await conn.execute(
        """
        select section_id, count(*) as students
          from chat_api.students
         where academic_year_status = 'active' and left_on is null
         group by section_id
        """
    )
    counts = {r["section_id"]: r["students"] for r in await cur.fetchall()}
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
