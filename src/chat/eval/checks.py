"""The checks of the evaluation: code that says pass or fail for one answer to one case (D007).

Each check knows the case, the answer text, the tools the graph called (with their arguments and
what the model read back) and the blocks the director saw. They need no model: the expected
answer is known in advance, because the bank runs on frozen data.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from chat.eval.bank import FILTERS, OUT_OF_SCOPE, Case


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict[str, Any]
    result: Any
    is_error: bool = False


@dataclass
class Answer:
    """What one run of the graph produced for one question."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None  # the codigo of an error block, if any


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


CHECK_NAMES = (
    "herramienta_esperada",
    "sin_filtros_no_pedidos",
    "argumentos_esperados",
    "hechos_presentes",
    "numeros_del_resultado",
    "nombres_oficiales",
    "sin_juicios",
    "menciona_el_periodo",
    "fuera_de_alcance",
    "pide_aclaracion",
)


def normalize(text: str) -> str:
    """Lowercase, without accents, one space between words: how the checks compare text."""
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )
    return re.sub(r"\s+", " ", stripped).strip().lower()


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# The official names of the levels are AD, A, B and C (Logro destacado, Logro esperado, En
# proceso, En inicio). These words were invented for them in the demo of 2026-10-31.
_INVENTED_LEVEL_WORDS = ("avanzado", "basico", "satisfactorio", "insuficiente", "sobresaliente")
# Judgements and recommendations the chat must not make (D003: report data, do not judge people).
_JUDGEMENTS = (
    r"\bbuen desempeno\b",
    r"\bmal desempeno\b",
    r"\baceptable\b",
    r"\bexcelente\b",
    r"\bpreocupante\b",
    r"\blamentable\b",
    r"\bflojo\b",
    r"\bflojos\b",
    r"\bdeficiente\b",
    r"\bdestaca\b",
    r"\bdestacan\b",
    r"\bva bien\b",
    r"\bva mal\b",
    r"\bvan mal\b",
    r"\brecomiend\w*",
    r"\bsugier\w*",
    r"\bconviene\b",
    r"\branking\b",
    r"\bel mejor alumno\b",
    r"\bel peor alumno\b",
)
# A numbered list of people: "1. Brenda Quispe", "2) Kevin Huamaní".
_NUMBERED_PEOPLE = re.compile(r"(?m)^\s*\d+[.)]\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+ [A-ZÁÉÍÓÚÑ]")
_ROMAN_ORDINAL = {"i": "primer", "ii": "segundo", "iii": "tercer", "iv": "cuarto"}


def run_checks(case: Case, answer: Answer) -> list[CheckResult]:
    """Every check that applies to the case, in a fixed order."""
    results = [
        _expected_tool(case, answer),
        _no_unasked_filters(case, answer),
        _expected_args(case, answer),
        _facts(case, answer),
        _numbers_from_results(case, answer),
        _official_level_names(answer),
        _no_judgements(answer),
    ]
    if case.period and not case.out_of_scope and not case.clarify:
        results.append(_mentions_period(answer))
    if case.out_of_scope:
        results.append(_out_of_scope(answer))
    if case.clarify:
        results.append(_asks_to_clarify(answer))
    return results


def passed(results: list[CheckResult]) -> bool:
    return all(r.passed for r in results)


def failures(results: list[CheckResult]) -> list[str]:
    return [r.name for r in results if not r.passed]


# --- the checks -----------------------------------------------------------------------------


def _expected_tool(case: Case, answer: Answer) -> CheckResult:
    first = answer.tool_calls[0].name if answer.tool_calls else None
    ok = first in case.tools
    want = " o ".join(t or "ninguna" for t in case.tools)
    return CheckResult("herramienta_esperada", ok, f"esperada {want}, usó {first or 'ninguna'}")


def _no_unasked_filters(case: Case, answer: Answer) -> CheckResult:
    """No tool call narrows the scope with a filter the question did not ask for."""
    unasked: list[str] = []
    for call in answer.tool_calls:
        for name in FILTERS:
            value = call.input.get(name)
            if value not in (None, "") and name not in case.args:
                unasked.append(f"{call.name}({name}={value!r})")
    return CheckResult(
        "sin_filtros_no_pedidos", not unasked, "; ".join(unasked) or "sin filtros de más"
    )


def _expected_args(case: Case, answer: Answer) -> CheckResult:
    """The first call to the expected tool carries the asked-for arguments."""
    if not case.args:
        return CheckResult("argumentos_esperados", True, "no se esperan argumentos")
    call = next((c for c in answer.tool_calls if c.name in case.tools), None)
    if call is None:
        return CheckResult("argumentos_esperados", False, "no hubo llamada a la herramienta")
    missing: list[str] = []
    for name, options in case.args.items():
        given = normalize(str(call.input.get(name) or ""))
        if not any(normalize(option) in given for option in options):
            missing.append(f"{name}={given!r} (esperado {'/'.join(options)})")
    return CheckResult("argumentos_esperados", not missing, "; ".join(missing) or "argumentos ok")


def _facts(case: Case, answer: Answer) -> CheckResult:
    text = normalize(answer.text)
    missing = [fact for fact in case.facts if normalize(fact) not in text]
    return CheckResult(
        "hechos_presentes", not missing, "faltan: " + ", ".join(missing) if missing else "todos"
    )


def _numbers_from_results(case: Case, answer: Answer) -> CheckResult:
    """Every number in the text came from a tool result, the question or the case's facts: the
    model copies figures, it never computes them (D007)."""
    allowed: set[str] = set()
    sources = [json.dumps(c.result, ensure_ascii=False, default=str) for c in answer.tool_calls]
    sources.append(case.question)
    sources.extend(case.facts)
    for source in sources:
        allowed.update(_canonical(n) for n in _NUMBER.findall(source))
    invented = sorted(
        {n for n in _NUMBER.findall(answer.text) if _canonical(n) not in allowed},
        key=lambda n: (len(n), n),
    )
    return CheckResult(
        "numeros_del_resultado",
        not invented,
        "no están en los datos: " + ", ".join(invented) if invented else "todos los números",
    )


def _canonical(number: str) -> str:
    """ "13,0" and "13.0" are "13"; "1.5" stays "1.5"."""
    value = number.replace(",", ".")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value or "0"


def _official_level_names(answer: Answer) -> CheckResult:
    text = normalize(answer.text)
    found = [w for w in _INVENTED_LEVEL_WORDS if re.search(rf"\b{w}\b", text)]
    return CheckResult(
        "nombres_oficiales", not found, "inventó: " + ", ".join(found) if found else "AD/A/B/C"
    )


def _no_judgements(answer: Answer) -> CheckResult:
    text = normalize(answer.text)
    found = [m.group(0) for pattern in _JUDGEMENTS if (m := re.search(pattern, text))]
    if _NUMBERED_PEOPLE.search(answer.text):
        found.append("lista numerada de personas")
    return CheckResult(
        "sin_juicios", not found, "juzga u ordena: " + ", ".join(found) if found else "solo datos"
    )


def _mentions_period(answer: Answer) -> CheckResult:
    """The answer names the period the tool used, by its full name or its short form."""
    names = {
        str(call.result[key])
        for call in answer.tool_calls
        if isinstance(call.result, dict)
        for key in ("periodo", "hasta_el_periodo", "con_los_niveles_de")
        if call.result.get(key)
    }
    if not names:
        return CheckResult("menciona_el_periodo", True, "la herramienta no fijó un periodo")
    text = normalize(answer.text)
    for name in names:
        if any(variant in text for variant in _period_variants(name)):
            return CheckResult("menciona_el_periodo", True, name)
    return CheckResult("menciona_el_periodo", False, "no nombra " + " / ".join(sorted(names)))


def _period_variants(name: str) -> list[str]:
    """ "Trimestre II" -> trimestre ii, t-ii, segundo trimestre."""
    base = normalize(name)
    variants = [base]
    kind, _, number = base.partition(" ")
    if kind and number:
        variants.append(f"{kind[0]}-{number}")
        if number in _ROMAN_ORDINAL:
            variants.append(f"{_ROMAN_ORDINAL[number]} {kind}")
    return variants


def _out_of_scope(answer: Answer) -> CheckResult:
    ok = normalize(OUT_OF_SCOPE) in normalize(answer.text)
    return CheckResult("fuera_de_alcance", ok, "frase fija" if ok else "no dio la frase fija")


def _asks_to_clarify(answer: Answer) -> CheckResult:
    """The answer asks, and names the options the tool offered (at least two of them)."""
    if "?" not in answer.text:
        return CheckResult("pide_aclaracion", False, "no pregunta")
    options: list[str] = []
    for call in answer.tool_calls:
        if isinstance(call.result, dict) and isinstance(call.result.get("opciones"), list):
            options.extend(str(o) for o in call.result["opciones"])
    if not options:
        return CheckResult("pide_aclaracion", True, "pregunta")
    text = normalize(answer.text)
    named = [o for o in options if normalize(o.split(" (")[0].split()[0]) in text]
    ok = len(named) >= min(2, len(options))
    return CheckResult("pide_aclaracion", ok, f"nombra {len(named)} de {len(options)} opciones")
