"""The six tools against tests/fixture_logros.sql: one case per rule of the glossary (D003),
the resolution of what the director wrote, and the isolation between schools."""

from typing import Any
from uuid import UUID

import pytest

from auth import Principal
from db import Database
from tests.conftest import TENANT_A, TENANT_B, USER_FLORES, USER_QUISPE
from tools import TOOL_STATUS, TOOLS, ToolOutcome, run_tool

DIRECTORS = {TENANT_A: USER_QUISPE, TENANT_B: USER_FLORES}


@pytest.fixture
def chat_url(databases: tuple[str, str]) -> str:
    return databases[0]


async def call(
    chat_url: str, name: str, args: dict[str, Any] | None = None, tenant: UUID = TENANT_A
) -> ToolOutcome:
    """The tool the way the chat runs it: as mawta_chat, inside the director's tenant."""
    db = Database(chat_url, max_size=1)
    await db.open()
    try:
        async with db.tenant_tx(Principal(DIRECTORS[tenant], tenant, "director")) as conn:
            return await run_tool(name, args or {}, conn)
    finally:
        await db.close()


def test_six_tools_each_with_a_status_and_closed_parameters():
    names = [t["function"]["name"] for t in TOOLS]
    assert names == [
        "datos_del_colegio",
        "resumen_de_niveles",
        "alumnos_con_c",
        "riesgo_por_competencia",
        "proyeccion_de_promocion",
        "historial_del_alumno",
    ]
    assert set(TOOL_STATUS) == set(names)
    for t in TOOLS:
        params = t["function"]["parameters"]
        assert params["additionalProperties"] is False
        assert params.get("required", []) == []


# --- datos_del_colegio ----------------------------------------------------------------------


async def test_school_data_lists_periods_sections_and_teachers(chat_url: str):
    out = await call(chat_url, "datos_del_colegio")

    assert out.result["colegio"] == "I.E. Cristo Rey"
    assert [(p["abreviatura"], p["estado"], p["es_el_actual"], p["tiene_niveles_de_logro"])
            for p in out.result["periodos"]] == [
        ("B-I", "cerrado", False, True),
        ("B-II", "cerrado", False, True),
        ("B-III", "cerrado", False, True),
        ("B-IV", "en curso", True, False),
    ]  # fmt: skip
    # By grade, not alphabetically; Iván left 3ro A, so it has 3 students.
    assert out.blocks[0]["tipo"] == "tabla"
    assert out.blocks[0]["filas"] == [
        ["Tercero de secundaria", "3ro A", "Mañana", "Marco Rojas", 3],
        ["Quinto de secundaria", "5to B", "Mañana", None, 5],
    ]
    assert {"seccion": "5to B", "area": "Matemática", "docente": "Janice Quispe"} in out.result[
        "docentes_por_clase"
    ]


async def test_school_data_only_sees_the_directors_school(chat_url: str):
    out = await call(chat_url, "datos_del_colegio", tenant=TENANT_B)

    assert out.result["colegio"] == "I.E. San Martín"
    assert [s["seccion"] for s in out.result["secciones"]] == ["5to A"]


# --- resumen_de_niveles ---------------------------------------------------------------------


async def test_summary_defaults_to_the_last_period_with_levels(chat_url: str):
    out = await call(chat_url, "resumen_de_niveles")

    assert out.result["periodo"] == "Bimestre III"  # B-IV is current but has no levels yet
    assert out.result["agrupado_por"] == "area"
    # Only live levels of área competencies: Elena's corrected C and her transversal C are out.
    assert out.result["totales"] == {"AD": 0, "A": 8, "B": 5, "C": 13}
    bars = out.blocks[0]
    assert bars["tipo"] == "barras_apiladas"
    assert bars["categorias"] == ["AD", "A", "B", "C"]
    assert bars["grupos"][0] == {"etiqueta": "Matemática", "valores": [0, 3, 2, 5]}


async def test_summary_of_an_area_by_competency_names_the_ones_without_levels(chat_url: str):
    out = await call(chat_url, "resumen_de_niveles", {"area": "mate", "periodo": "bimestre 2"})

    assert out.result["periodo"] == "Bimestre II"
    assert out.result["agrupado_por"] == "competencia"
    assert [g["grupo"] for g in out.result["grupos"]] == [
        "MAT-C1 · Resuelve problemas de cantidad",
        "MAT-C2 · Resuelve problemas de regularidad, equivalencia y cambio",
    ]
    assert out.result.get("competencias_sin_nivel", []) == []


async def test_summary_by_section(chat_url: str):
    out = await call(chat_url, "resumen_de_niveles", {"agrupar_por": "seccion"})

    assert [(g["grupo"], g["C"]) for g in out.result["grupos"]] == [("3ro A", 10), ("5to B", 3)]


async def test_a_period_without_levels_says_so_instead_of_inventing(chat_url: str):
    out = await call(chat_url, "resumen_de_niveles", {"periodo": "actual"})

    assert out.result["periodo"] == "Bimestre IV"
    assert "todavía no tiene niveles" in out.result["sin_datos"]
    assert out.blocks == []


async def test_a_school_with_no_levels_at_all_has_no_data(chat_url: str):
    out = await call(chat_url, "alumnos_con_c", tenant=TENANT_B)

    assert "sin_datos" in out.result and "necesita_aclaracion" not in out.result


# --- alumnos_con_c --------------------------------------------------------------------------


async def test_students_with_c_by_section_then_surname(chat_url: str):
    out = await call(chat_url, "alumnos_con_c")

    assert out.result["alumnos_con_C"] == 5
    assert out.result["total_de_C"] == 13
    assert [(row[0], row[1], row[2]) for row in out.blocks[0]["filas"]] == [
        ("Fabiola Flores Gil", "3ro A", 8),
        ("Gabriel Gomez Huaman", "3ro A", 2),
        ("Ana Alvarez Ruiz", "5to B", 1),
        ("Bruno Bravo Soto", "5to B", 1),
        ("Carla Cordova Ttito", "5to B", 1),
    ]
    # Elena's corrected C (now A) does not count.
    assert all("Elena" not in row[0] for row in out.blocks[0]["filas"])


async def test_students_with_c_in_a_section_and_area(chat_url: str):
    out = await call(chat_url, "alumnos_con_c", {"seccion": "5B", "periodo": "B-I"})

    assert out.result["alcance"].startswith("5to B")
    assert [r["alumno"] for r in out.result["filas"]] == [
        "Ana Alvarez Ruiz",
        "Bruno Bravo Soto",
        "Diego Diaz Uscamayta",
    ]


# --- riesgo_por_competencia -----------------------------------------------------------------


async def test_risk_counts_consecutive_c_and_a_period_without_level_breaks_it(chat_url: str):
    out = await call(chat_url, "riesgo_por_competencia")

    assert out.result["hasta_el_periodo"] == "Bimestre III"
    assert [(r["alumno"], r["competencia"][:6], r["racha"], r["periodos"])
            for r in out.result["filas"]] == [
        ("Ana Alvarez Ruiz", "MAT-C1", 3, ["B-I", "B-II", "B-III"]),
        ("Carla Cordova Ttito", "MAT-C2", 2, ["B-II", "B-III"]),
    ]  # fmt: skip
    # Bruno: C, —, C (broken). Diego: C, C, B (ends in B). Fabiola: one period only.
    assert out.result["alumnos_en_riesgo"] == 2
    assert out.blocks[0]["columnas"] == ["Alumno", "Sección", "Competencia", "Racha", "Periodos"]


async def test_risk_with_a_longer_minimum(chat_url: str):
    out = await call(chat_url, "riesgo_por_competencia", {"minimo": 3})

    assert [r["alumno"] for r in out.result["filas"]] == ["Ana Alvarez Ruiz"]


# --- proyeccion_de_promocion ----------------------------------------------------------------


async def test_promotion_projection_follows_the_area_rule(chat_url: str):
    out = await call(chat_url, "proyeccion_de_promocion")

    assert out.result["es_proyeccion"] is True
    assert out.result["con_los_niveles_de"] == "Bimestre III"
    assert [(r["alumno"], r["areas_no_aprobadas"], r["situacion_proyectada"])
            for r in out.result["filas"]] == [
        ("Fabiola Flores Gil", ["Matemática", "Comunicación", "Inglés", "Ciencia y Tecnología"],
         "en riesgo de permanecer"),
        # EPT has one competency, in C; CYT has one C of two, so half is B or above: passed.
        ("Gabriel Gomez Huaman", ["Educación para el Trabajo"], "iría a recuperación"),
    ]  # fmt: skip
    assert out.result["alumnos_por_situacion"] == {
        "promovería": 1,
        "iría a recuperación": 1,
        "en riesgo de permanecer": 1,
    }
    # 5to has another rule: no projection for it, and the tool says so.
    assert out.result["grados_sin_proyeccion"] == ["Quinto de secundaria"]


async def test_promotion_for_a_grade_without_the_rule(chat_url: str):
    out = await call(chat_url, "proyeccion_de_promocion", {"grado": "quinto"})

    assert out.result.get("filas", []) == []
    assert "Quinto de secundaria" in out.result["aviso"]


# --- historial_del_alumno -------------------------------------------------------------------


async def test_student_history_is_a_matrix_with_empty_cells_for_no_level(chat_url: str):
    out = await call(chat_url, "historial_del_alumno", {"alumno": "ana alvarez"})

    assert out.result["alumno"] == "Ana Alvarez Ruiz"
    assert out.result["cantidad_de_C_por_periodo"] == {"B-I": 1, "B-II": 1, "B-III": 1, "B-IV": 0}
    matrix = out.blocks[0]
    assert matrix["tipo"] == "matriz"
    assert matrix["columnas"] == ["B-I", "B-II", "B-III", "B-IV"]
    assert [(f["grupo"], f["etiqueta"][:6], f["celdas"]) for f in matrix["filas"]] == [
        ("Matemática", "MAT-C1", ["C", "C", "C", None]),
        ("Matemática", "MAT-C2", [None, None, None, None]),
    ]


async def test_student_history_shows_only_the_live_level(chat_url: str):
    out = await call(chat_url, "historial_del_alumno", {"alumno": "Elena"})

    cells = {f["etiqueta"][:6]: f["celdas"] for f in out.blocks[0]["filas"]}
    assert cells["MAT-C1"] == [None, None, "A", None]
    assert "TR-C1" not in cells  # transversal competencies are not área competencies


async def test_student_history_of_a_student_who_left(chat_url: str):
    out = await call(chat_url, "historial_del_alumno", {"alumno": "Iván Ibarra"})

    assert out.result["seccion"] == "3ro A"
    assert out.result["retirado_de_la_seccion_el"] == "2026-09-01"


async def test_student_history_asks_which_student(chat_url: str):
    ambiguous = await call(chat_url, "historial_del_alumno", {"alumno": "Huaman"})
    missing = await call(chat_url, "historial_del_alumno")
    unknown = await call(chat_url, "historial_del_alumno", {"alumno": "Zoila Zapata"})

    assert ambiguous.result["opciones"] == [
        "Gabriel Gomez Huaman (3ro A)",
        "Hilda Huaman Inca (3ro A)",
    ]
    assert "necesita_aclaracion" in missing.result
    assert "No encontré" in unknown.result["necesita_aclaracion"]


async def test_a_student_of_another_school_is_not_found(chat_url: str):
    out = await call(chat_url, "historial_del_alumno", {"alumno": "Ana Alvarez"}, tenant=TENANT_B)

    assert "No encontré" in out.result["necesita_aclaracion"]


# --- resolution and validation --------------------------------------------------------------


@pytest.mark.parametrize(
    ("periodo", "expected"),
    [
        ("B-II", "Bimestre II"),
        ("segundo bimestre", "Bimestre II"),
        ("bimestre i", "Bimestre I"),
        ("último cerrado", "Bimestre III"),
    ],
)
async def test_periods_are_read_the_way_the_director_writes_them(
    chat_url: str, periodo: str, expected: str
):
    out = await call(chat_url, "alumnos_con_c", {"periodo": periodo})

    assert out.result["periodo"] == expected


async def test_an_unknown_grade_or_area_answers_with_the_options(chat_url: str):
    grade = await call(chat_url, "alumnos_con_c", {"grado": "primero"})
    area = await call(chat_url, "alumnos_con_c", {"area": "robótica"})

    assert grade.result["opciones"] == ["Tercero de secundaria", "Quinto de secundaria"]
    assert "Matemática" in area.result["opciones"]


async def test_arguments_outside_the_schema_are_a_tool_error(chat_url: str):
    unknown = await call(chat_url, "alumnos_con_c", {"turno": "mañana"})
    wrong_type = await call(chat_url, "riesgo_por_competencia", {"minimo": "dos"})
    bad_enum = await call(chat_url, "resumen_de_niveles", {"agrupar_por": "docente"})
    no_tool = await call(chat_url, "secciones_del_colegio")

    assert all(o.is_error for o in (unknown, wrong_type, bad_enum, no_tool))
