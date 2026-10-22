"""The chat's tools. Each reads only chat_api views, inside the director's
tenant transaction, so RLS decides what it can see.

A tool returns two things: the result for the model, and the blocks the
director sees directly (a table built from the database, never from the
model's text — the model does not retype numbers).
"""

from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow

SHIFTS = {
    "manana": "Mañana",
    "tarde": "Tarde",
    "noche": "Noche",
    "completo": "Completo",
}


@dataclass
class ToolOutcome:
    result: dict[str, Any]
    blocks: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False


SECTIONS_TOOL: dict[str, Any] = {
    "name": "secciones_del_colegio",
    "description": (
        "Lists the sections of the director's school: academic year, grade, "
        "section, shift and status. Use it for any question about the school's "
        'sections, grades or classrooms ("salones").'
    ),
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    "eager_input_streaming": True,
}

TOOLS = [SECTIONS_TOOL]


async def school_sections(conn: AsyncConnection[DictRow]) -> ToolOutcome:
    cur = await conn.execute(
        """
        select academic_year, grade_long, section, shift, status
          from chat_api.sections
         order by academic_year desc, grade_long, section
        """
    )
    rows = await cur.fetchall()
    result = {"secciones": rows, "total": len(rows)}
    table = {
        "tipo": "tabla",
        "titulo": "Secciones del colegio",
        "columnas": ["Año", "Grado", "Sección", "Turno", "Estado"],
        "filas": [
            [
                r["academic_year"],
                r["grade_long"],
                r["section"],
                SHIFTS.get(r["shift"], r["shift"]),
                "Activa" if r["status"] == "active" else "Archivada",
            ]
            for r in rows
        ],
        "nota": "Fuente: secciones registradas en Mawta.",
    }
    return ToolOutcome(result=result, blocks=[table] if rows else [])


async def run_tool(name: str, tool_input: Any, conn: AsyncConnection[DictRow]) -> ToolOutcome:
    if name == "secciones_del_colegio":
        if tool_input not in ({}, None):
            return ToolOutcome(result={"error": "this tool takes no input"}, is_error=True)
        return await school_sections(conn)
    return ToolOutcome(result={"error": f"unknown tool {name!r}"}, is_error=True)


TOOL_STATUS = {"secciones_del_colegio": "Consultando las secciones del colegio…"}
