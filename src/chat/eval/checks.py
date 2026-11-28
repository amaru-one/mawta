"""The checks of the evaluation: code that says pass or fail for one answer to one case.

Each check knows the case, the answer text, the tools the graph called (with their arguments and
what the model read back) and the blocks the director saw. They need no model: the expected
answer is known in advance, because the bank runs on frozen data.

The hard rules stay hard: no number that is not in a tool result, the official level names, the
period named, and no ranking or judgement of people. Analysis and suggestions about áreas,
competencies, sections and management are welcome, and an answer may chain several tools.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from chat.eval.bank import FILTERS, OUT_OF_SCOPE, Case
from chat.tools import SCOPE_TOOLS


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
    # Calls of earlier answers in the same thread: a follow-up may quote their figures.
    earlier_calls: list[ToolCall] = field(default_factory=list)


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
# A whole number written with thousands separators: "1.094", "1,094", "1 094" (no-break or narrow
# space). The tools write 1094; the school-wide totals are this large.
_GROUPED = re.compile(r"(?<!\d)(?<!\d[.,])\d{1,3}(?:[.,\u00a0\u202f]\d{3})+(?!\d|[.,]\d)")


def _ungroup(text: str) -> str:
    """ "1.094 C" -> "1094 C"."""
    return _GROUPED.sub(lambda m: re.sub(r"\D", "", m.group(0)), text)


def _numbers(text: str) -> set[str]:
    """Every number the text writes, canonical: "1.094" is 1094 and "20,0" is 20."""
    return {_canonical(n) for n in _NUMBER.findall(_ungroup(text))}


# The official names of the levels are AD, A, B and C (Logro destacado, Logro esperado, En
# proceso, En inicio). These words were invented for them in the demo of 2026-10-31.
_INVENTED_LEVEL_WORDS = ("avanzado", "basico", "satisfactorio", "insuficiente", "sobresaliente")
# Judgements of people the chat must not make: ranking, praising or criticising students
# or teachers. Judging data is allowed: "Matemática bajó", "conviene revisar", "recomiendo una
# reunión" are analysis and suggestions, not judgements of anyone.
_PERSON = (
    r"(?:alumn\w*|estudiant\w*|docent\w*|profesor\w*|maestr\w*|tutor(?:a|es|as)?\b|nin[oa]s?\b)"
)
_JUDGEMENTS = (
    rf"\b(?:el|la|los|las)\s+(?:\d+\s+)?(?:mejor|peor|mejores|peores)\s+{_PERSON}",
    rf"\b(?:mejor|peor|mejores|peores)\s+{_PERSON}\s+(?:de|del)\b",
    rf"\b(?:buen|buena|buenos|buenas|mal|mala|malos|malas|excelente|excelentes|pesimo|pesima"
    rf"|pesimos|pesimas)\s+{_PERSON}",
    rf"\b{_PERSON}\s+(?:es|son|fue|era)\s+(?:muy\s+)?(?:bueno|buena|buenos|buenas|malo|mala|malos"
    rf"|malas|excelente|excelentes|flojo|floja|flojos|flojas|brillante|brillantes|deficiente"
    rf"|deficientes|incapaz|incapaces|pesimo|pesima)\b",
    r"\bflojo\b",
    r"\bflojos\b",
    r"\bfloja\b",
    r"\bflojas\b",
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
    """The answer used one of the expected tools, alone or with others (looking up the periods
    first, or a closer look after a summary). None in case.tools accepts an answer with no tool.
    A scope tool nobody expected fails: it means the chat refused or gave up on a question it
    could answer. An out-of-scope case takes fuera_de_alcance alone."""
    used = [c.name for c in answer.tool_calls]
    want = " o ".join(t or "ninguna" for t in case.tools)
    detail = f"esperada {want}, usó {', '.join(used) or 'ninguna'}"
    stray = [n for n in used if n in SCOPE_TOOLS and n not in case.tools]
    if case.out_of_scope:
        ok = bool(used) and set(used) <= set(case.tools)
    elif not used:
        ok = None in case.tools
    else:
        ok = any(n in case.tools for n in used) and not stray
    return CheckResult("herramienta_esperada", ok, detail)


def _no_unasked_filters(case: Case, answer: Answer) -> CheckResult:
    """No tool call narrows the scope with a filter the question did not ask for. A section
    names its grade too ("1B" is primero B), so a grado next to an asked-for section is asked.
    A filter whose value came out of an earlier result of the same answer is a closer look, not
    an invented filter: the área that went down in comparar_periodos, then its students."""
    asked = set(case.args)
    if "seccion" in asked:
        asked.add("grado")
    unasked: list[str] = []
    seen = ""  # the normalized results read so far in this answer
    for call in answer.tool_calls:
        for name in FILTERS:
            value = call.input.get(name)
            if value in (None, "") or name in asked:
                continue
            if seen and normalize(str(value)) in seen:
                continue
            unasked.append(f"{call.name}({name}={value!r})")
        if not call.is_error:
            seen += " " + normalize(json.dumps(call.result, ensure_ascii=False, default=str))
    return CheckResult(
        "sin_filtros_no_pedidos", not unasked, "; ".join(unasked) or "sin filtros de más"
    )


def _expected_args(case: Case, answer: Answer) -> CheckResult:
    """The last call to the expected tool, the one the answer comes from, carries the asked-for
    arguments. A first call the tool answered with a clarification ("1" is primaria or
    secundaria) and a second, corrected call is a right answer."""
    if not case.args:
        return CheckResult("argumentos_esperados", True, "no se esperan argumentos")
    call = next((c for c in reversed(answer.tool_calls) if c.name in case.tools), None)
    if call is None:
        if None in case.tools:
            return CheckResult("argumentos_esperados", True, "respondió sin herramienta")
        return CheckResult("argumentos_esperados", False, "no hubo llamada a la herramienta")
    missing: list[str] = []
    for name, options in case.args.items():
        given = normalize(str(call.input.get(name) or ""))
        if not any(normalize(option) in given for option in options):
            missing.append(f"{name}={given!r} (esperado {'/'.join(options)})")
    return CheckResult("argumentos_esperados", not missing, "; ".join(missing) or "argumentos ok")


_MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre")  # fmt: skip
_NUMBER_WORDS = {
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
}  # fmt: skip


def _readable(text: str) -> str:
    """The normalized text plus the other spellings of what it says: a date written 2026-12-18
    or 18/12/2026 also reads "18 de diciembre", and "nueve" also reads "9". ("uno"/"una" are
    left out: they are articles far more often than numbers.)"""
    extra: list[str] = []
    for y, m, d in re.findall(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text):
        if 1 <= int(m) <= 12:
            extra.append(f"{int(d)} de {_MONTHS[int(m) - 1]} de {y}")
    for d, m, y in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
        if 1 <= int(m) <= 12:
            extra.append(f"{int(d)} de {_MONTHS[int(m) - 1]} de {y}")
    for word, number in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            extra.append(str(number))
    return " ".join([text, *extra])


def _facts(case: Case, answer: Answer) -> CheckResult:
    """Every fact must appear; "a|b" accepts either spelling, and dates and small numbers count
    in any of their usual spellings. A fact that is a number must be a whole number of the text:
    "20" is not found in "220", and "1094" is found in "1.094"."""
    text = _readable(normalize(_ungroup(answer.text)))
    numbers = _numbers(text)

    def found(option: str) -> bool:
        if option.isdigit():
            return _canonical(option) in numbers
        return normalize(option) in text

    missing = [fact for fact in case.facts if not any(found(o) for o in fact.split("|"))]
    return CheckResult(
        "hechos_presentes", not missing, "faltan: " + ", ".join(missing) if missing else "todos"
    )


def _numbers_from_results(case: Case, answer: Answer) -> CheckResult:
    """Every number in the text came from a tool result (of this answer or an earlier one of the
    thread), the question or the case's facts: the model copies figures, percentages and
    variations, it never computes them."""
    allowed: set[str] = set()
    sources = [
        json.dumps(c.result, ensure_ascii=False, default=str)
        for c in [*answer.earlier_calls, *answer.tool_calls]
    ]
    sources.append(case.question)
    sources.extend(case.facts)
    for source in sources:
        allowed.update(_canonical(n) for n in _NUMBER.findall(source))
    invented = sorted(
        {n for n in _NUMBER.findall(_ungroup(answer.text)) if _canonical(n) not in allowed},
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


# A sentence that says the chat does not do it: "no puedo decir quiénes son los mejores alumnos".
_NEGATION = re.compile(r"\b(?:no|nunca|ni|sin)\b")


def _no_judgements(answer: Answer) -> CheckResult:
    """No judgement of people, sentence by sentence; a sentence that declines to judge ("no
    hago rankings de los mejores alumnos") does not count."""
    found: list[str] = []
    for sentence in re.split(r"[.!?;\n]+", normalize(answer.text)):
        for pattern in _JUDGEMENTS:
            m = re.search(pattern, sentence)
            if m and not _NEGATION.search(sentence[: m.start()]):
                found.append(m.group(0))
    if _NUMBERED_PEOPLE.search(answer.text):
        found.append("lista numerada de personas")
    return CheckResult(
        "sin_juicios",
        not found,
        "juzga u ordena personas: " + ", ".join(found) if found else "sin juicios de personas",
    )


def _mentions_period(answer: Answer) -> CheckResult:
    """The answer names the period the tool used, by its full name or its short form."""
    names = {
        str(call.result[key])
        for call in answer.tool_calls
        if isinstance(call.result, dict)
        for key in (
            "periodo",
            "hasta_el_periodo",
            "con_los_niveles_de",
            "periodo_inicial",
            "periodo_final",
        )
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
