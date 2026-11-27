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


def test_the_expected_tool_must_be_among_the_calls():
    good = Answer("20 alumnos en el Trimestre II.", [call()])
    assert check(JALADOS, good, "herramienta_esperada").passed
    other = Answer("…", [call("resumen_de_niveles")])
    assert not check(JALADOS, other, "herramienta_esperada").passed
    none = Answer("No lo sé.")
    assert not check(JALADOS, none, "herramienta_esperada").passed
    no_tool_case = Case("y", "¿Faltas?", "adversarial", tools=(None,))
    assert check(no_tool_case, none, "herramienta_esperada").passed
    assert not check(no_tool_case, good, "herramienta_esperada").passed


def test_several_tools_in_one_answer_pass_when_one_is_expected():
    # A summary first, then the students of the área that stood out.
    chained = Answer("…", [call("resumen_de_niveles"), call(area="Matemática")])
    assert check(JALADOS, chained, "herramienta_esperada").passed
    looked_up_periods = Answer("…", [call("datos_del_colegio"), call()])
    assert check(JALADOS, looked_up_periods, "herramienta_esperada").passed
    # Giving up on a question the tools answer is not composition.
    gave_up = Answer("…", [call(), call("sin_herramienta", {"tema": "jalados"})])
    assert not check(JALADOS, gave_up, "herramienta_esperada").passed
    # An out-of-scope case takes fuera_de_alcance alone.
    scope = Case("z", "¿Almuerzo?", "adversarial", tools=("fuera_de_alcance",),
                 out_of_scope=True, period=False)  # fmt: skip
    assert check(scope, Answer("…", [call("fuera_de_alcance", {})]), "herramienta_esperada").passed
    assert not check(
        scope, Answer("…", [call(), call("fuera_de_alcance", {})]), "herramienta_esperada"
    ).passed


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
    assert check(JALADOS, Answer("…", [call(mostrar_bloque=True)]), "sin_filtros_no_pedidos").passed


def test_a_filter_taken_from_an_earlier_result_is_a_closer_look():
    summary = call("comparar_periodos", {"grupos": [{"grupo": "Matemática"}]})
    closer = Answer("…", [summary, call(area="Matemática")])
    assert check(JALADOS, closer, "sin_filtros_no_pedidos").passed
    # The same filter with nothing before it is still invented, and so is a value no result had.
    assert not check(
        JALADOS, Answer("…", [call(area="Matemática")]), "sin_filtros_no_pedidos"
    ).passed
    elsewhere = Answer("…", [summary, call(area="Inglés")])
    assert not check(JALADOS, elsewhere, "sin_filtros_no_pedidos").passed


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


def test_the_figures_of_comparisons_and_percentages_count_as_data():
    compared = call(
        "comparar_periodos",
        {"periodo_inicial": "Trimestre I", "periodo_final": "Trimestre II",
         "totales": {"inicial": {"porcentaje_C": 12.5}, "final": {"porcentaje_C": 9.3},
                     "variacion": {"porcentaje_C": -3.2, "alumnos_con_C": -4}}},
    )  # fmt: skip
    text = "Del Trimestre I al II, la C bajó de 12,5 % a 9,3 % (-3,2 puntos; 4 alumnos menos)."
    assert check(JALADOS, Answer(text, [compared]), "numeros_del_resultado").passed
    # Working out a difference the tool did not state is still inventing it.
    own = Answer("La C bajó 3 puntos y medio, de 12,5 % a 9 %.", [compared])
    assert not check(JALADOS, own, "numeros_del_resultado").passed
    # A follow-up may quote the figures of an earlier answer of the thread.
    follow_up = Answer("Sí: 9,3 % en el Trimestre II.", earlier_calls=[compared])
    assert check(JALADOS, follow_up, "numeros_del_resultado").passed
    assert check(JALADOS, Answer("En el Trimestre II…", [compared]), "menciona_el_periodo").passed


def test_invented_level_names_fail():
    assert check(JALADOS, Answer("Hay 20 con C (En inicio)."), "nombres_oficiales").passed
    bad = check(JALADOS, Answer("B (Básico) y AD (Avanzado)."), "nombres_oficiales")
    assert not bad.passed and "basico" in bad.detail and "avanzado" in bad.detail


def test_judging_or_ranking_people_fails():
    assert check(JALADOS, Answer("1ro A tiene 48 C y 1ro B 54."), "sin_juicios").passed
    for text in (
        "Brenda es el mejor alumno de primero.",
        "Estos son los 5 mejores alumnos de 1A.",
        "Los peores estudiantes de 1B son Kevin y Brenda.",
        "El profesor es malo.",
        "Es un mal docente: sus alumnos tienen muchas C.",
        "Hay alumnos flojos en 3ro A.",
        "1. Brenda Quispe\n2. Kevin Huamaní",
    ):
        assert not check(JALADOS, Answer(text), "sin_juicios").passed, text
    # "Logro destacado" is the official name of AD, not a judgement.
    assert check(JALADOS, Answer("5 con AD (Logro destacado)."), "sin_juicios").passed


def test_analysis_and_suggestions_are_not_judgements():
    for text in (
        "Recomiendo una reunión con los docentes de Matemática para revisar MAT-C1.",
        "Te sugiero priorizar Comunicación: es la que más subió en C.",
        "Conviene revisar las competencias sin nivel.",
        "Es preocupante que 3ro A concentre 10 C; destaca la baja en Inglés.",
        "El desempeño en Matemática es aceptable y va mejor que en el Bimestre II.",
        "La sección muestra buen desempeño en Comunicación.",
        "No hago rankings de los mejores alumnos, pero puedo listar quiénes tienen AD.",
    ):
        assert check(JALADOS, Answer(text), "sin_juicios").passed, text


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


def test_facts_accept_alternatives():
    case = Case("x", "q", "adversarial", facts=("asistencia|tardanza",))
    assert check(case, Answer("Mawta aún no registra las tardanzas."), "hechos_presentes").passed
    assert not check(case, Answer("No lo sé."), "hechos_presentes").passed


def test_a_grade_next_to_an_asked_section_is_not_an_unasked_filter():
    case = Case("x", "¿C en 1B?", "d003", tools=("alumnos_con_c",), args={"seccion": ("1b", "b")})
    answer = Answer("…", [call(grado="1", seccion="B")])
    assert check(case, answer, "sin_filtros_no_pedidos").passed
    assert not check(
        case, Answer("…", [call(area="Inglés", seccion="B")]), "sin_filtros_no_pedidos"
    ).passed


def test_a_refusal_that_mentions_a_ranking_is_not_a_ranking():
    answer = Answer("No puedo hacer un ranking, pero puedo listar quiénes tienen AD.")
    assert check(JALADOS, answer, "sin_juicios").passed


def test_expected_arguments_pass_when_answering_without_a_tool_is_allowed():
    case = Case("x", "q", "adversarial", tools=("alumnos_con_c", None), args={"area": ("mat",)})
    assert check(case, Answer("No juzgo a docentes."), "argumentos_esperados").passed


def test_facts_read_dates_and_numbers_in_their_usual_spellings():
    case = Case("x", "q", "d003", facts=("18 de diciembre", "9"))
    for text in (
        "Termina el 2026-12-18; irían 9.",
        "Termina el 18/12/2026; irían nueve.",
        "Termina el 18 de diciembre; Nueve irían a recuperación.",
    ):
        assert check(case, Answer(text), "hechos_presentes").passed, text
    assert not check(case, Answer("Termina el 2026-12-19; irían ocho."), "hechos_presentes").passed


def test_a_number_fact_is_a_whole_number_of_the_text():
    case = Case("x", "q", "d003", facts=("20",))
    assert check(case, Answer("Son 20 alumnos."), "hechos_presentes").passed
    assert not check(case, Answer("Son 220 alumnos."), "hechos_presentes").passed
    assert not check(case, Answer("Hay 120 C."), "hechos_presentes").passed


def test_large_numbers_count_with_or_without_thousands_separators():
    case = Case("x", "q", "d003", facts=("1094",))
    result = {"periodo": "Trimestre II", "totales_de_niveles": {"C": 1094, "B": 5744}}
    for text in ("Hay 1094 C.", "Hay 1.094 C.", "Hay 1,094 C.", "Hay 1 094 C."):
        answer = Answer(f"{text} B: 5.744.", [call(result=result)])
        assert check(case, answer, "hechos_presentes").passed, text
        assert check(case, answer, "numeros_del_resultado").passed, text
    # A decimal is not a thousands separator, and a date is not a number with separators.
    assert not check(case, Answer("Hay 1,09 C."), "hechos_presentes").passed
    assert not check(case, Answer("Hay 1.094,5 C."), "hechos_presentes").passed


def test_the_arguments_are_judged_on_the_call_the_answer_comes_from():
    case = Case(
        "x", "¿Primero de secundaria?", "d003", tools=("resumen_de_niveles",),
        args={"grado": ("secundaria",)},
    )  # fmt: skip
    asked_again = Answer(
        "…",
        [call("resumen_de_niveles", grado="1"),
         call("resumen_de_niveles", grado="Primero de Secundaria")],
    )  # fmt: skip
    assert check(case, asked_again, "argumentos_esperados").passed
    lost_it = Answer(
        "…",
        [call("resumen_de_niveles", grado="Primero de Secundaria"),
         call("resumen_de_niveles", grado="1")],
    )  # fmt: skip
    assert not check(case, lost_it, "argumentos_esperados").passed
