"""The evaluation's checks, each on its own, without a model or a database (D007)."""

from typing import Any

from chat.eval.bank import OUT_OF_SCOPE, Case
from chat.eval.checks import Answer, ToolCall, normalize, run_checks

RESULT = {
    "periodo": "Trimestre II",
    "alcance": "todo el colegio",
    "alumnos_con_C": 20,
    "total_de_C": 102,
    "filas": [{"alumno": "Brenda Quispe Condori", "cantidad_de_C": 14}],
}


def call(name: str = "alumnos_con_c", result: Any = None, **args: Any) -> ToolCall:
    return ToolCall(name, args, RESULT if result is None else result)


def check(case: Case, answer: Answer, name: str):
    return next(r for r in run_checks(case, answer) if r.name == name)


def names(case: Case, answer: Answer) -> list[str]:
    return [r.name for r in run_checks(case, answer)]


JALADOS = Case("x", "¿Quiénes están jalados?", "d003", tools=("alumnos_con_c",), facts=("20",))


def test_normalize_drops_accents_case_and_spacing():
    assert normalize("  Matemática\n  en 1ro  A ") == "matematica en 1ro a"


def test_the_expected_tool_is_the_first_one_called():
    good = Answer("20 alumnos en el Trimestre II.", [call()])
    assert check(JALADOS, good, "herramienta_esperada").passed
    other = Answer("…", [call("resumen_de_niveles")])
    assert not check(JALADOS, other, "herramienta_esperada").passed
    none = Answer("No lo sé.")
    assert not check(JALADOS, none, "herramienta_esperada").passed
    no_tool_case = Case("y", "¿Faltas?", "adversarial", tools=(None,))
    assert check(no_tool_case, none, "herramienta_esperada").passed
    assert not check(no_tool_case, good, "herramienta_esperada").passed


def test_filters_nobody_asked_for_fail():
    # The 2026-10-31 failure: "¿Quiénes están en riesgo?" answered for 1ro A and Matemática.
    answer = Answer("…", [call(seccion="1A", area="Matemática")])
    result = check(JALADOS, answer, "sin_filtros_no_pedidos")
    assert not result.passed and "seccion" in result.detail and "area" in result.detail
    asked = Case(
        "x", "¿Jalados en mate?", "d003", tools=("alumnos_con_c",), args={"area": ("mat",)}
    )
    assert check(asked, Answer("…", [call(area="Matemática")]), "sin_filtros_no_pedidos").passed
    # Non-filter parameters are free.
    assert check(JALADOS, Answer("…", [call(periodo="T-II")]), "sin_filtros_no_pedidos").passed


def test_expected_arguments_accept_any_of_their_spellings():
    case = Case(
        "x", "¿C en mate?", "d003", tools=("alumnos_con_c",), args={"area": ("matem", "mat")}
    )
    assert check(case, Answer("…", [call(area="Matemática")]), "argumentos_esperados").passed
    assert check(case, Answer("…", [call(area="MAT")]), "argumentos_esperados").passed
    assert not check(case, Answer("…", [call(area="Inglés")]), "argumentos_esperados").passed
    assert not check(case, Answer("…", [call()]), "argumentos_esperados").passed
    assert not check(case, Answer("…"), "argumentos_esperados").passed


def test_facts_must_appear_regardless_of_accents_and_case():
    case = Case("x", "q", "d003", facts=("Brenda Quispe", "14"))
    assert check(case, Answer("brenda quispe tiene 14 C"), "hechos_presentes").passed
    missing = check(case, Answer("Tiene 14 C"), "hechos_presentes")
    assert not missing.passed and "Brenda Quispe" in missing.detail


def test_every_number_in_the_text_must_come_from_the_data():
    data = Answer("Son 20 alumnos con 102 C en el Trimestre II (14 de Brenda).", [call()])
    assert check(JALADOS, data, "numeros_del_resultado").passed
    invented = Answer("Son 569 estudiantes.", [call()])
    result = check(JALADOS, invented, "numeros_del_resultado")
    assert not result.passed and "569" in result.detail
    # Numbers from the question itself are fine; "20,0" is 20.
    asked = Case("x", "¿Cuántos de los 56 alumnos…?", "d003", tools=("alumnos_con_c",))
    assert check(
        asked, Answer("De los 56, 20,0 tienen C.", [call()]), "numeros_del_resultado"
    ).passed
    # Dates and percentages inside the result count as data too.
    pct = Answer("13 % de C.", [call(result={"porcentaje_C": 13})])
    assert check(JALADOS, pct, "numeros_del_resultado").passed


def test_invented_level_names_fail():
    assert check(JALADOS, Answer("Hay 20 con C (En inicio)."), "nombres_oficiales").passed
    bad = check(JALADOS, Answer("B (Básico) y AD (Avanzado)."), "nombres_oficiales")
    assert not bad.passed and "basico" in bad.detail and "avanzado" in bad.detail


def test_judgements_rankings_and_recommendations_fail():
    assert check(JALADOS, Answer("1ro A tiene 48 C y 1ro B 54."), "sin_juicios").passed
    for text in (
        "La sección muestra buen desempeño.",
        "El desempeño es aceptable.",
        "Recomiendo reforzar matemática.",
        "1. Brenda Quispe\n2. Kevin Huamaní",
        "Brenda destaca en arte.",
    ):
        assert not check(JALADOS, Answer(text), "sin_juicios").passed, text
    # "Logro destacado" is the official name of AD, not a judgement.
    assert check(JALADOS, Answer("5 con AD (Logro destacado)."), "sin_juicios").passed


def test_the_period_may_be_named_in_full_short_or_ordinal_form():
    for text in ("En el Trimestre II…", "En T-II…", "En el segundo trimestre…"):
        assert check(JALADOS, Answer(text, [call()]), "menciona_el_periodo").passed, text
    assert not check(JALADOS, Answer("Son 20.", [call()]), "menciona_el_periodo").passed
    # A tool that fixed no period (datos_del_colegio) asks nothing of the text.
    school = Answer("Dos secciones.", [call("datos_del_colegio", result={"secciones": []})])
    assert check(JALADOS, school, "menciona_el_periodo").passed
    # Other tools name their period under other keys.
    risk = Answer(
        "Hasta el Trimestre II.", [call("riesgo", result={"hasta_el_periodo": "Trimestre II"})]
    )
    assert check(JALADOS, risk, "menciona_el_periodo").passed


def test_out_of_scope_needs_the_fixed_phrase_word_for_word():
    case = Case("x", "¿Almuerzo?", "adversarial", out_of_scope=True, period=False)
    assert check(case, Answer(OUT_OF_SCOPE), "fuera_de_alcance").passed
    assert check(case, Answer(f"Lo siento. {OUT_OF_SCOPE}"), "fuera_de_alcance").passed
    assert not check(case, Answer("No puedo ayudarte con eso."), "fuera_de_alcance").passed


def test_a_clarification_asks_and_names_the_options():
    case = Case(
        "x",
        "¿Cómo va Quispe?",
        "aclaracion",
        tools=("historial_del_alumno",),
        clarify=True,
        period=False,
    )
    options = {
        "necesita_aclaracion": "Hay varios alumnos.",
        "opciones": ["Brenda Quispe Condori (1ro A)", "Camila Torres Quispe (1ro A)"],
    }
    good = Answer(
        "¿Te refieres a Brenda Quispe o a Camila Torres?", [call("historial_del_alumno", options)]
    )
    assert check(case, good, "pide_aclaracion").passed
    one = Answer("¿Brenda Quispe?", [call("historial_del_alumno", options)])
    assert not check(case, one, "pide_aclaracion").passed
    assert not check(
        case,
        Answer("Brenda tiene 14 C.", [call("historial_del_alumno", options)]),
        "pide_aclaracion",
    ).passed


def test_which_checks_apply_depends_on_the_case():
    base = {"herramienta_esperada", "sin_filtros_no_pedidos", "argumentos_esperados",
            "hechos_presentes", "numeros_del_resultado", "nombres_oficiales", "sin_juicios"}  # fmt: skip
    assert set(names(JALADOS, Answer("x"))) == base | {"menciona_el_periodo"}
    scope = Case("x", "q", "adversarial", out_of_scope=True, period=False)
    assert set(names(scope, Answer("x"))) == base | {"fuera_de_alcance"}
    clarify = Case("x", "q", "aclaracion", clarify=True)
    assert set(names(clarify, Answer("x"))) == base | {"pide_aclaracion"}
