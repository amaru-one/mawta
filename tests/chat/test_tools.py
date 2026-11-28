"""The data tools against tests/fixtures_levels.py: one case per rule of the glossary, the
resolution of what the director wrote, and when a tool shows its block (mostrar_bloque)."""

from collections.abc import Iterator
from typing import Any

import pytest

from chat.tools import REGISTRY, TOOL_STATUS, TOOLS, TOPICS, ToolOutcome, block_requested, run_tool
from chat.tools.base import MOSTRAR_BLOQUE, Clarify, Param, Tool, shown
from chat.tools.compare_periods import pick_terms, variation
from chat.tools.levels import Group, percentages
from chat.tools.promotion import Area, project_end_of_cycle, project_mid_cycle, rule_for
from chat.tools.resolve import resolve_section
from db import Database, RequestCtx
from tests import fixtures
from tests.chat.conftest import ANA
from tests.conftest import Databases, migrated_database


@pytest.fixture
def chat_url(databases: Databases) -> str:
    return databases.app_url


@pytest.fixture(scope="module")
def school_without_levels() -> Iterator[str]:
    """The test school alone: no period has achievement levels yet."""
    with migrated_database([fixtures.load]) as dbs:
        yield dbs.app_url


async def call(
    chat_url: str, name: str, args: dict[str, Any] | None = None, *, show: bool = False
) -> ToolOutcome:
    """The tool the way the chat runs it: as mawta_chat, for a director. show passes
    mostrar_bloque=true, the way the model asks to show the block."""
    db = Database(chat_url, pool_size=1)
    args = {**(args or {}), **({"mostrar_bloque": True} if show else {})}
    try:
        async with db.chat_tx(RequestCtx(actor_id=ANA, role="director")) as conn:
            return await run_tool(name, args, conn)
    finally:
        await db.close()


def test_nine_tools_each_with_a_status_and_closed_parameters():
    names = [t["function"]["name"] for t in TOOLS]
    assert names == [
        "datos_del_colegio",
        "resumen_de_niveles",
        "comparar_periodos",
        "alumnos_con_c",
        "riesgo_por_competencia",
        "proyeccion_de_promocion",
        "historial_del_alumno",
        "fuera_de_alcance",
        "sin_herramienta",
    ]
    assert set(TOOL_STATUS) == set(names)
    for t in TOOLS:
        params = t["function"]["parameters"]
        assert params["additionalProperties"] is False
        assert params.get("required", []) == []


def test_every_data_tool_can_show_its_block_and_names_its_topic():
    """The scope tools show nothing and look nothing up; every other tool has mostrar_bloque
    (a boolean, off by default) and a topic for the system prompt's list."""
    for name, tool in REGISTRY.items():
        is_scope = name in ("fuera_de_alcance", "sin_herramienta")
        assert tool.shows_blocks is not is_scope, name
        assert (name in TOPICS) is not is_scope, name
        if not is_scope:
            prop = tool.spec()["function"]["parameters"]["properties"]["mostrar_bloque"]
            assert prop["type"] == "boolean"


def test_mostrar_bloque_is_a_boolean_and_only_true_shows():
    tool = Tool("x", "x", "x", {"mostrar_bloque": MOSTRAR_BLOQUE, "n": Param("n")}, run=None)  # type: ignore[arg-type]
    assert tool.check({"mostrar_bloque": True}) == {"mostrar_bloque": True}
    assert tool.check({"mostrar_bloque": "false"}) == {"mostrar_bloque": False}
    assert tool.check({"mostrar_bloque": "TRUE"}) == {"mostrar_bloque": True}
    with pytest.raises(ValueError, match="true or false"):
        tool.check({"mostrar_bloque": "sí"})
    with pytest.raises(ValueError, match="true or false"):
        tool.check({"mostrar_bloque": 1})
    block = {"tipo": "tabla"}
    assert shown({}, block) == []
    assert shown({"mostrar_bloque": False}, block) == []
    assert shown({"mostrar_bloque": True}, block, None) == [block]
    assert block_requested({"mostrar_bloque": True}) and block_requested({"mostrar_bloque": "true"})
    assert not block_requested({}) and not block_requested(None)
    assert not block_requested({"mostrar_bloque": "false"})


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("datos_del_colegio", {}),
        ("resumen_de_niveles", {}),
        ("comparar_periodos", {}),
        ("alumnos_con_c", {}),
        ("riesgo_por_competencia", {}),
        ("proyeccion_de_promocion", {}),
        ("historial_del_alumno", {"alumno": "ana alvarez"}),
    ],
)
async def test_a_tool_shows_its_block_only_when_asked(
    chat_url: str, tool: str, args: dict[str, Any]
):
    silent = await call(chat_url, tool, args)
    explicit = await call(chat_url, tool, {**args, "mostrar_bloque": False})
    asked = await call(chat_url, tool, args, show=True)

    assert silent.blocks == [] and explicit.blocks == []
    assert silent.result["bloque_mostrado"] is False
    assert len(asked.blocks) == 1 and asked.result["bloque_mostrado"] is True
    # The model reads the same data either way.
    assert {k: v for k, v in silent.result.items() if k != "bloque_mostrado"} == {
        k: v for k, v in asked.result.items() if k != "bloque_mostrado"
    }


# --- datos_del_colegio ----------------------------------------------------------------------


async def test_school_data_lists_periods_sections_and_teachers(chat_url: str):
    out = await call(chat_url, "datos_del_colegio", show=True)

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
        ["Segundo de secundaria", "2do A", "Mañana", None, 4],
        ["Tercero de secundaria", "3ro A", "Mañana", "Marco Rojas", 3],
        ["Quinto de secundaria", "5to B", "Mañana", None, 5],
    ]
    assert {"seccion": "5to B", "area": "Matemática", "docente": "Janice Quispe"} in out.result[
        "docentes_por_clase"
    ]


# --- resumen_de_niveles ---------------------------------------------------------------------


async def test_summary_defaults_to_the_last_period_with_levels(chat_url: str):
    out = await call(chat_url, "resumen_de_niveles", show=True)

    assert out.result["periodo"] == "Bimestre III"  # B-IV is current but has no levels yet
    assert out.result["agrupado_por"] == "area"
    # Only live levels of área competencies: Elena's corrected C and her transversal C are out.
    assert out.result["totales_de_niveles"] == {"AD": 0, "A": 24, "B": 20, "C": 18}
    bars = out.blocks[0]
    assert bars["tipo"] == "barras_apiladas"
    assert bars["categorias"] == ["AD", "A", "B", "C"]
    assert bars["grupos"][0] == {"etiqueta": "Matemática", "valores": [0, 8, 4, 6]}


async def test_summary_counts_students_apart_from_levels(chat_url: str):
    """The 2026-10-31 demo read 569 levels as students: the tool now says how many
    students were evaluated and how many have a C, overall and per group."""
    out = await call(chat_url, "resumen_de_niveles", show=True)
    with_c = await call(chat_url, "alumnos_con_c")

    assert out.result["alumnos_con_C"] == with_c.result["alumnos_con_C"]
    assert 0 < out.result["alumnos_con_C"] <= out.result["alumnos_evaluados"]
    assert sum(out.result["totales_de_niveles"].values()) > out.result["alumnos_evaluados"]
    mat = next(g for g in out.result["grupos"] if g["grupo"] == "Matemática")
    assert mat["total_niveles"] == 18 and 0 < mat["alumnos_con_C"] <= mat["alumnos"]
    assert "alumnos evaluados" in out.blocks[0]["nota"]
    assert "no alumnos" in out.result["regla"]


async def test_summary_gives_the_percentage_of_every_level_per_group_and_in_total(chat_url: str):
    out = await call(chat_url, "resumen_de_niveles")

    # 62 levels: AD 0, A 24, B 20, C 18.
    assert out.result["porcentajes_totales"] == {
        "porcentaje_AD": 0.0,
        "porcentaje_A": 38.7,
        "porcentaje_B": 32.3,
        "porcentaje_C": 29.0,
        "porcentaje_logro": 38.7,
    }
    mat = next(g for g in out.result["grupos"] if g["grupo"] == "Matemática")
    # Matemática: AD 0, A 8, B 4, C 6 of 18.
    assert {k: mat[k] for k in mat if k.startswith("porcentaje")} == {
        "porcentaje_AD": 0.0,
        "porcentaje_A": 44.4,
        "porcentaje_B": 22.2,
        "porcentaje_C": 33.3,
        "porcentaje_logro": 44.4,
    }
    for g in out.result["grupos"]:
        assert g == {**g, **percentages([g["AD"], g["A"], g["B"], g["C"]])}, g["grupo"]


def test_percentages_have_one_decimal_and_logro_is_a_plus_ad():
    assert percentages([1, 2, 3, 0]) == {
        "porcentaje_AD": 16.7,
        "porcentaje_A": 33.3,
        "porcentaje_B": 50.0,
        "porcentaje_C": 0.0,
        "porcentaje_logro": 50.0,
    }
    assert percentages([0, 0, 0, 0])["porcentaje_logro"] == 0.0


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

    assert [(g["grupo"], g["C"]) for g in out.result["grupos"]] == [
        ("2do A", 5),
        ("3ro A", 10),
        ("5to B", 3),
    ]


async def test_a_period_without_levels_reports_the_last_one_with_levels_and_says_so(
    chat_url: str,
):
    """The demo model fills periodo="actual" nobody asked for (2026-11-16): instead of «no data»,
    the tool reports the last period with levels and tells the model why."""
    for tool in ("resumen_de_niveles", "alumnos_con_c"):
        out = await call(chat_url, tool, {"periodo": "actual"}, show=True)

        assert out.result["periodo"] == "Bimestre III", tool
        assert "Bimestre IV todavía no tiene niveles" in out.result["aviso_periodo"], tool
        assert "sin_datos" not in out.result and out.blocks, tool


async def test_a_school_with_no_levels_at_all_has_no_data(school_without_levels: str):
    out = await call(school_without_levels, "alumnos_con_c")

    assert "sin_datos" in out.result and "necesita_aclaracion" not in out.result


# --- comparar_periodos ----------------------------------------------------------------------


def _term(seq: int, has_levels: bool = True, current: bool = False) -> dict[str, Any]:
    return {"id": seq, "sequence": seq, "name": f"Bimestre {'I' * seq}", "short_name": f"B-{seq}",
            "status": "active" if current else "closed", "is_current": current,
            "has_levels": has_levels}  # fmt: skip


TERMS = [_term(1), _term(2), _term(3), _term(4, has_levels=False, current=True)]


def test_the_periods_to_compare():
    def names(picked: Any) -> Any:
        return picked if isinstance(picked, str) else [t["sequence"] for t in picked]

    assert names(pick_terms(TERMS, None, None)) == [2, 3]  # the last two with levels
    assert names(pick_terms(TERMS, "B-1", None)) == [1, 3]  # with the last one with levels
    assert names(pick_terms(TERMS, None, "B-1")) == [1, 3]
    assert names(pick_terms(TERMS, "B-3", None)) == [2, 3]  # the last one: with the one before
    assert names(pick_terms(TERMS, "B-3", "B-1")) == [1, 3]  # always in order
    assert "todavía no tiene niveles" in pick_terms(TERMS, "B-4", None)
    assert "todavía no tiene niveles" in pick_terms(TERMS, "actual", "B-1")
    assert "Solo Bimestre I" in pick_terms([_term(1), _term(2, has_levels=False)], None, None)
    assert "Ningún periodo" in pick_terms([_term(1, has_levels=False)], None, None)
    with pytest.raises(Clarify) as same:
        pick_terms(TERMS, "B-2", "segundo bimestre")
    assert same.value.options == ["Bimestre I", "Bimestre II", "Bimestre III"]


def test_a_variation_is_the_difference_of_the_stated_figures():
    before = Group("x", [1, 2, 3, 0], students=6, students_with_c=0)  # 16.7 / 33.3 / 50 / 0
    after = Group("x", [0, 1, 1, 1], students=3, students_with_c=1)  # 0 / 33.3 / 33.3 / 33.3
    assert variation(before, after) == {
        "porcentaje_AD": -16.7,
        "porcentaje_A": 0.0,
        "porcentaje_B": -16.7,
        "porcentaje_C": 33.3,
        "porcentaje_logro": -16.7,
        "alumnos_con_C": 1,
        "alumnos_evaluados": -3,
    }


async def test_comparing_defaults_to_the_last_two_periods_with_levels(chat_url: str):
    out = await call(chat_url, "comparar_periodos")
    before = await call(chat_url, "resumen_de_niveles", {"periodo": "B-II"})
    after = await call(chat_url, "resumen_de_niveles", {"periodo": "B-III"})

    assert (out.result["periodo_inicial"], out.result["periodo_final"]) == (
        "Bimestre II",
        "Bimestre III",
    )
    assert out.result["agrupado_por"] == "area"
    totals = out.result["totales"]
    assert totals["final"]["porcentaje_C"] == after.result["porcentajes_totales"]["porcentaje_C"]
    assert totals["inicial"]["alumnos_con_C"] == before.result["alumnos_con_C"]
    assert totals["final"]["alumnos_evaluados"] == after.result["alumnos_evaluados"]
    for key in (
        "porcentaje_AD",
        "porcentaje_A",
        "porcentaje_B",
        "porcentaje_C",
        "porcentaje_logro",
    ):
        assert totals["variacion"][key] == round(
            after.result["porcentajes_totales"][key] - before.result["porcentajes_totales"][key], 1
        ), key
    assert totals["variacion"]["alumnos_con_C"] == (
        after.result["alumnos_con_C"] - before.result["alumnos_con_C"]
    )
    # Every group present in both periods carries its own exact variation.
    groups_after = {g["grupo"]: g for g in after.result["grupos"]}
    groups_before = {g["grupo"]: g for g in before.result["grupos"]}
    for g in out.result["grupos"]:
        if g["grupo"] in groups_after and g["grupo"] in groups_before:
            a, b = groups_after[g["grupo"]], groups_before[g["grupo"]]
            assert g["final"]["C"] == a["C"] and g["inicial"]["C"] == b["C"]
            assert g["variacion"]["porcentaje_logro"] == round(
                a["porcentaje_logro"] - b["porcentaje_logro"], 1
            )
            assert g["variacion"]["alumnos_con_C"] == a["alumnos_con_C"] - b["alumnos_con_C"]
        else:
            assert "variacion" not in g and g["grupo"] in out.result["solo_en_un_periodo"]
    assert out.blocks == []


async def test_comparing_named_periods_with_filters_and_grouping(chat_url: str):
    out = await call(
        chat_url,
        "comparar_periodos",
        {
            "periodo_inicial": "B-I",
            "periodo_final": "B-III",
            "area": "mate",
            "seccion": "3ro A",
        },  # fmt: skip
    )
    after = await call(
        chat_url, "resumen_de_niveles", {"periodo": "B-III", "area": "mate", "seccion": "3ro A"}
    )

    assert (out.result["periodo_inicial"], out.result["periodo_final"]) == (
        "Bimestre I",
        "Bimestre III",
    )
    assert out.result["alcance"] == after.result["alcance"]
    assert out.result["agrupado_por"] == "competencia"
    assert out.result["totales"]["final"]["C"] == after.result["totales_de_niveles"]["C"]
    by_section = await call(chat_url, "comparar_periodos", {"agrupar_por": "seccion"})
    assert {g["grupo"] for g in by_section.result["grupos"]} <= {"2do A", "3ro A", "5to B"}


async def test_comparing_a_period_without_levels_has_no_data(
    chat_url: str, school_without_levels: str
):
    current = await call(chat_url, "comparar_periodos", {"periodo_final": "actual"})
    nothing = await call(school_without_levels, "comparar_periodos")
    same = await call(chat_url, "comparar_periodos", {"periodo_inicial": "B-II",
                                                       "periodo_final": "B-II"})  # fmt: skip

    assert "Bimestre IV todavía no tiene niveles" in current.result["sin_datos"]
    assert "sin_datos" in nothing.result
    assert "bloque_mostrado" not in current.result
    assert "necesita_aclaracion" in same.result


async def test_the_comparison_table_has_a_row_per_group_and_a_total(chat_url: str):
    out = await call(chat_url, "comparar_periodos", show=True)

    table = out.blocks[0]
    assert table["tipo"] == "tabla"
    assert table["columnas"][:4] == ["Área", "% A+AD B-II", "% A+AD B-III", "Var. A+AD"]
    assert [row[0] for row in table["filas"]] == [
        *(g["grupo"] for g in out.result["grupos"]),
        "Total",
    ]
    total = out.result["totales"]
    assert table["filas"][-1][1:3] == [
        total["inicial"]["porcentaje_logro"],
        total["final"]["porcentaje_logro"],
    ]
    change = total["variacion"]["porcentaje_C"]
    assert table["filas"][-1][6] == (f"{change:+.1f}" if change else "0.0")


# --- alumnos_con_c --------------------------------------------------------------------------


async def test_students_with_c_by_section_then_surname(chat_url: str):
    out = await call(chat_url, "alumnos_con_c", show=True)

    assert out.result["alumnos_con_C"] == 7
    assert out.result["total_de_C"] == 18
    assert [(row[0], row[1], row[2]) for row in out.blocks[0]["filas"]] == [
        ("Luis Medina Nuñez", "2do A", 1),
        ("Marta Núñez Ortiz", "2do A", 4),
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
    out = await call(chat_url, "riesgo_por_competencia", show=True)

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


async def test_promotion_projection_applies_the_rule_of_each_grade(chat_url: str):
    out = await call(chat_url, "proyeccion_de_promocion", show=True)

    assert out.result["es_proyeccion"] is True
    assert out.result["con_los_niveles_de"] == "Bimestre III"
    assert "1.°, 3.° y 4.°" in out.result["regla"] and "2.° y 5.°" in out.result["regla"]
    situations = {r["alumno"]: r["situacion_proyectada"] for r in out.result["filas"]}
    assert situations == {
        # 2do A, end of cycle. Julia (no C, half in A/AD in 3 áreas) is promoted, so not listed.
        "Kiara Lazo Mena": "iría a recuperación",  # all B: no área with half in A or AD
        "Luis Medina Nuñez": "iría a recuperación",  # one C is enough to miss promotion
        "Marta Núñez Ortiz": "en riesgo de permanecer",  # C in exactly half of 4 áreas
        # 3ro A, mid cycle. Hilda (all A) is promoted.
        "Fabiola Flores Gil": "en riesgo de permanecer",
        # EPT has one competency, in C; CYT has one C of two, so half is B or above: passed.
        "Gabriel Gomez Huaman": "iría a recuperación",
        # 5to B closes a cycle too, and has only Matemática: no 3 áreas to promote with.
        "Ana Alvarez Ruiz": "iría a recuperación",
        "Bruno Bravo Soto": "iría a recuperación",
        "Carla Cordova Ttito": "iría a recuperación",
        "Diego Diaz Uscamayta": "iría a recuperación",
        "Elena Espinoza Vilca": "iría a recuperación",
    }
    assert out.result["alumnos_por_situacion"] == {
        "promovería": 2,
        "iría a recuperación": 8,
        "en riesgo de permanecer": 2,
    }
    assert "grados_sin_proyeccion" not in out.result
    gabriel = next(r for r in out.result["filas"] if r["alumno"].startswith("Gabriel"))
    assert gabriel["areas_no_aprobadas"] == ["Educación para el Trabajo"]
    assert out.blocks[0]["columnas"] == ["Alumno", "Sección", "Situación proyectada", "Motivo"]


async def test_promotion_of_one_grade_states_only_its_rule(chat_url: str):
    out = await call(chat_url, "proyeccion_de_promocion", {"grado": "segundo"})

    assert [r["alumno"] for r in out.result["filas"]] == [
        "Kiara Lazo Mena",
        "Luis Medina Nuñez",
        "Marta Núñez Ortiz",
    ]
    assert "2.° y 5.°" in out.result["regla"] and "1.°, 3.° y 4.°" not in out.result["regla"]
    marta = out.result["filas"][2]
    assert marta["areas_con_C_en_la_mitad_o_mas"] == [
        "Matemática",
        "Comunicación",
        "Inglés",
        "Ciencia y Tecnología",
    ]


def area(name: str, *levels: str) -> Area:
    return Area(
        name,
        with_level=len(levels),
        a_or_above=sum(lv in ("AD", "A") for lv in levels),
        b_or_above=sum(lv != "C" for lv in levels),
        c=levels.count("C"),
    )


def test_the_same_levels_project_differently_mid_cycle_and_at_its_end():
    # C in exactly half of the competencies of four áreas (cuadro 5.1.3.A, RVM 048-2024).
    marta = [area("MAT", "C", "A"), area("COM", "C", "B"), area("ING", "C", "A"),
             area("CYT", "C", "B"), area("EPT", "A")]  # fmt: skip
    assert project_mid_cycle(marta).situation == "promovería"  # half is B or above
    assert project_end_of_cycle(marta).situation == "en riesgo de permanecer"  # half is C

    all_b = [area(n, "B", "B") for n in ("MAT", "COM", "ING", "CYT")]
    assert project_mid_cycle(all_b).situation == "promovería"
    assert project_end_of_cycle(all_b).situation == "iría a recuperación"
    assert "ninguna área" in project_end_of_cycle(all_b).reason


def test_mid_cycle_repeats_from_four_areas_with_more_than_half_c():
    three = [area(n, "C", "C", "B") for n in ("MAT", "COM", "ING")] + [area("CYT", "A")]
    four = [area(n, "C", "C", "B") for n in ("MAT", "COM", "ING", "CYT")]
    assert project_mid_cycle(three).situation == "iría a recuperación"
    assert project_mid_cycle(four).situation == "en riesgo de permanecer"


def test_end_of_cycle_promotes_with_three_areas_in_a_and_no_c():
    three_a = [area("MAT", "A", "B"), area("COM", "AD", "A"), area("ING", "A"), area("CYT", "B")]
    two_a = [area("MAT", "A", "B"), area("COM", "AD", "A"), area("ING", "B"), area("CYT", "B")]
    assert project_end_of_cycle(three_a).situation == "promovería"
    assert project_end_of_cycle(two_a).situation == "iría a recuperación"


@pytest.mark.parametrize(
    ("stage", "position", "rule"),
    [
        ("secundaria", 1, "mid"),
        ("secundaria", 3, "mid"),
        ("secundaria", 4, "mid"),
        ("secundaria", 2, "end"),
        ("secundaria", 5, "end"),
        ("primaria", 3, None),
        (None, 1, None),
    ],
)
def test_the_rule_of_each_grade(stage: str | None, position: int, rule: str | None):
    assert rule_for(stage, position) == rule


# --- historial_del_alumno -------------------------------------------------------------------


async def test_student_history_is_a_matrix_with_empty_cells_for_no_level(chat_url: str):
    out = await call(chat_url, "historial_del_alumno", {"alumno": "ana alvarez"}, show=True)

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
    out = await call(chat_url, "historial_del_alumno", {"alumno": "Elena"}, show=True)

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


async def test_a_name_that_matches_no_student_is_not_found(chat_url: str):
    out = await call(chat_url, "historial_del_alumno", {"alumno": "Xiomara Quintanilla"})

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

    assert grade.result["opciones"] == [
        "Segundo de secundaria",
        "Tercero de secundaria",
        "Quinto de secundaria",
    ]
    assert "Matemática" in area.result["opciones"]


async def test_arguments_outside_the_schema_are_a_tool_error(chat_url: str):
    unknown = await call(chat_url, "alumnos_con_c", {"turno": "mañana"})
    wrong_type = await call(chat_url, "riesgo_por_competencia", {"minimo": "dos"})
    bad_enum = await call(chat_url, "resumen_de_niveles", {"agrupar_por": "docente"})
    no_tool = await call(chat_url, "secciones_del_colegio")

    assert all(o.is_error for o in (unknown, wrong_type, bad_enum, no_tool))


def _section(grade: str, grade_long: str, stage: str, letter: str) -> dict[str, Any]:
    return {"grade": grade, "grade_long": grade_long, "stage": stage, "section": letter,
            "name": f"{grade} {letter} de {stage}"}  # fmt: skip


BOTH_STAGES = [
    _section("1ro", "Primero de Primaria", "primaria", "A"),
    _section("1ro", "Primero de Primaria", "primaria", "B"),
    _section("1ro", "Primero de Secundaria", "secundaria", "A"),
    _section("1ro", "Primero de Secundaria", "secundaria", "B"),
]


def test_a_section_with_its_stage_is_found_when_both_stages_have_it():
    sec = resolve_section(BOTH_STAGES, "1B de secundaria")
    prim = resolve_section(BOTH_STAGES, "1ro B de primaria")

    assert sec["name"] == "1ro B de secundaria"
    assert prim["name"] == "1ro B de primaria"


def test_a_section_without_its_stage_asks_which_when_both_stages_have_it():
    with pytest.raises(Clarify) as asked:
        resolve_section(BOTH_STAGES, "1B")

    assert asked.value.options == [
        "1ro B de primaria (Primero de Primaria)",
        "1ro B de secundaria (Primero de Secundaria)",
    ]


def test_students_are_broken_down_by_stage_and_section_without_repeats():
    from chat.tools.base import students_by_group

    rows = [
        {"student_id": 1, "stage": "primaria", "section_name": "1ro A de primaria"},
        {"student_id": 1, "stage": "primaria", "section_name": "1ro A de primaria"},
        {"student_id": 2, "stage": "primaria", "section_name": "4to B de primaria"},
        {"student_id": 3, "stage": "secundaria", "section_name": "1ro A de secundaria"},
    ]

    assert students_by_group(rows) == {
        "alumnos_por_nivel_educativo": {"primaria": 2, "secundaria": 1},
        "alumnos_por_seccion": {
            "1ro A de primaria": 1,
            "4to B de primaria": 1,
            "1ro A de secundaria": 1,
        },
    }
    assert students_by_group(rows[:2]) == {}


def test_a_grade_that_carries_a_section_letter_is_read_as_a_section():
    from chat.tools.resolve import names_a_section

    assert names_a_section("1B de secundaria")
    assert names_a_section("1ro B")
    assert not names_a_section("Primero de Secundaria")
    assert not names_a_section("5to de secundaria")
    assert not names_a_section("1ro")


def test_a_stage_counts_only_when_the_director_named_it():
    from chat.tools.resolve import stage_named

    assert not stage_named("¿Cuántos C hay en 1B?")
    assert not stage_named("¿Cuántos jalados hay en la sección B?")
    assert stage_named("¿Cuántos C hay en 1B de secundaria?")
    assert stage_named("¿Cómo va primero de prim?")
    assert stage_named("1ro B sec")
    assert stage_named("¿Y en Primaria?")


def test_a_stage_the_director_did_not_name_is_dropped_from_the_arguments():
    from chat.tools.resolve import drop_unsaid_stage

    sent = {"seccion": "1ro B de secundaria", "grado": "Primero de Primaria", "area": "MAT"}

    assert drop_unsaid_stage(sent, "¿Cuántos C hay en 1B?") == {
        "seccion": "1ro B",
        "grado": "Primero",
        "area": "MAT",
    }
    assert drop_unsaid_stage(sent, "¿Cuántos C hay en 1B de secundaria?") == sent
    assert drop_unsaid_stage({"periodo": "T-II"}, "¿Y en el T-II?") == {"periodo": "T-II"}
    assert drop_unsaid_stage(None, "1B") is None
