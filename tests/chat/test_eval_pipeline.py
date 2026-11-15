"""The evaluation pipeline end to end on the test school with the scripted model: the graph runs,
the checks judge, the summary counts. No Langfuse, no demo checkout."""

import re
from typing import Any

from chat.eval import runner
from chat.eval.bank import Case
from tests.chat.conftest import FakeLLM, text_turn, tool_turn
from tests.conftest import Databases, make_settings

SECTIONS = Case(
    "test-secciones",
    "¿Qué secciones tiene mi colegio?",
    "d003",
    tools=("datos_del_colegio",),
    facts=("5to B",),
    period=False,
    source="tests/fixtures.py: Cristo Rey has 2do A, 3ro A and 5to B",
)
OUT = Case("test-almuerzo", "¿Qué hay de almuerzo?", "adversarial", period=False, out_of_scope=True)


async def test_the_bank_runs_through_the_graph_and_the_checks_judge_each_answer(
    databases: Databases, tmp_path: Any
):
    fake = FakeLLM()
    # Repetition 1: both cases right. Repetition 2: the first one invents a filter and a number.
    fake.script(
        tool_turn(),
        text_turn("Tu colegio tiene tres secciones: 2do A, 3ro A y 5to B."),
        text_turn(
            "Solo puedo ayudarte con datos de tu colegio: secciones, niveles de logro y alumnos "
            "en riesgo. ¿Quieres consultar algo de eso?"
        ),
        tool_turn(name="resumen_de_niveles", arguments='{"seccion": "5to B"}'),
        text_turn("Son 569 estudiantes con buen desempeño."),
        text_turn("No puedo."),
    )
    settings = make_settings(databases, tmp_path)
    lines: list[str] = []

    runs = await runner.run_bank(
        settings,
        [SECTIONS, OUT],
        repeat=2,
        run_name="test",
        langfuse=False,
        llm=fake,
        log_line=lines.append,
    )

    assert [(r.case.id, r.repeat, r.passed) for r in runs] == [
        ("test-secciones", 1, True),
        ("test-almuerzo", 1, True),
        ("test-secciones", 2, False),
        ("test-almuerzo", 2, False),
    ]
    bad = runs[2]
    assert set(bad.failures) == {
        "herramienta_esperada",
        "sin_filtros_no_pedidos",
        "hechos_presentes",
        "numeros_del_resultado",
        "sin_juicios",
    }
    assert bad.answer.tool_calls[0].name == "resumen_de_niveles"
    assert runs[3].failures == ["fuera_de_alcance"]
    assert runs[0].trace_id is None and runs[0].latency_ms >= 0
    assert len(lines) == 4 and lines[0].startswith("  [1/2] ok  ") and "FALLA" in lines[2]

    text = runner.summary(runs)
    assert re.search(r"test-secciones\s+1/2", text)
    assert re.search(r"fuera_de_alcance\s+1/2", text)
    assert "Total: 2/4" in text and "(50.0 %)" in text
    assert runner.pass_rate(runs) == 50.0
    assert '"pass_rate": 50.0' in runner.to_json(runs, "local:fake", "test")
    # Each repetition is its own LangGraph thread: the second run saw no history.
    assert [m["role"] for m in fake.calls[3]] == ["user"]
