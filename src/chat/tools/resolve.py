"""How the director's words become the school's own periods, grades, sections, áreas and
students (D003, glossary): "este trimestre", "los de primero", "1A", "mate", "Brenda Quispe".

Everything is resolved against the active academic year of the school in the session, read from
chat_api. Nothing matches → the valid options; several match → the candidates. Either way the
tool answers with Clarify and the model asks the director.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Table, select
from sqlalchemy.ext.asyncio import AsyncConnection

from chat.tools.base import Clarify, NoData, fetch_rows
from mawta_schema import api_views as v

ORDINALS = {
    "primero": 1, "primer": 1, "primera": 1, "segundo": 2, "segunda": 2, "tercero": 3,
    "tercer": 3, "tercera": 3, "cuarto": 4, "cuarta": 4, "quinto": 5, "quinta": 5,
    "sexto": 6, "sexta": 6,
}  # fmt: skip
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}
CURRENT_WORDS = ("actual", "este", "esta", "ahora", "en curso")
LAST_CLOSED_WORDS = ("ultimo cerrado", "ultimo", "anterior", "pasado")
# Common short names of the áreas; anything else is matched against the school's own names.
AREA_ALIASES = {
    "mate": "MAT", "matematica": "MAT", "matematicas": "MAT",
    "comu": "COM", "comunicacion": "COM", "lenguaje": "COM",
    "ingles": "ING",
    "sociales": "CCSS", "historia": "CCSS", "ciencias sociales": "CCSS",
    "ciencia": "CYT", "ciencias": "CYT", "cta": "CYT", "ciencia y tecnologia": "CYT",
    "arte": "ARTE", "artes": "ARTE",
    "religion": "ER",
    "educacion fisica": "EF", "deporte": "EF", "fisica": "EF",
    "civica": "DPCC", "ciudadania": "DPCC", "persona": "DPCC", "dpcc": "DPCC",
    "trabajo": "EPT", "ept": "EPT",
}  # fmt: skip


def norm(text: str) -> str:
    """Lowercase, no accents, single spaces: how every comparison is made."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    plain = plain.replace("°", " ").replace("º", " ")
    return " ".join(plain.split())


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+", norm(text))


def number_in(text: str, roman: bool = True) -> int | None:
    """The first number the text names: "2", "segundo", "ii", "t-2", "1ro"."""
    for tok in tokens(text):
        if tok.isdigit():
            return int(tok)
        if tok in ORDINALS:
            return ORDINALS[tok]
        if roman and tok in ROMAN:
            return ROMAN[tok]
    return None


# --- periods --------------------------------------------------------------------------------


async def terms(conn: AsyncConnection) -> list[dict[str, Any]]:
    t = v.terms.c
    return await fetch_rows(
        conn,
        select(
            t.id,
            t.academic_year,
            t.sequence,
            t.name,
            t.short_name,
            t.starts_on,
            t.ends_on,
            t.status,
            t.is_current,
            t.has_levels,
        )  # fmt: skip
        .where(t.academic_year_status == "active")
        .order_by(t.sequence),
    )


def label(term: dict[str, Any]) -> str:
    return term["short_name"] or term["name"]


def last_with_levels(all_terms: list[dict[str, Any]]) -> dict[str, Any] | None:
    with_levels = [t for t in all_terms if t["has_levels"]]
    return with_levels[-1] if with_levels else None


def resolve_term(all_terms: list[dict[str, Any]], text: str | None) -> dict[str, Any]:
    """A period of the active year. Without text: the last one with levels (levels are asserted
    when a period closes, so the one in progress usually has none)."""
    if not all_terms:
        raise NoData("El colegio no tiene periodos registrados en el año activo.")
    options = [label(t) if label(t) == t["name"] else f"{label(t)} ({t['name']})"
               for t in all_terms]  # fmt: skip
    if not text or not text.strip():
        term = last_with_levels(all_terms)
        if term is None:
            raise NoData(
                "Ningún periodo del año activo tiene todavía niveles de logro: los docentes los "
                "registran al cerrar cada periodo."
            )
        return term
    t = norm(text)
    if any(w in t for w in LAST_CLOSED_WORDS) and number_in(t) is None:
        closed = [x for x in all_terms if x["status"] in ("closed", "archived")]
        if closed:
            return closed[-1]
        raise Clarify("Todavía no hay periodos cerrados en el año activo.", options)
    if any(t.startswith(w) or f" {w} " in f" {t} " for w in CURRENT_WORDS) and number_in(t) is None:
        current = [x for x in all_terms if x["is_current"]]
        if current:
            return current[0]
        raise Clarify("Hoy no cae dentro de ningún periodo del año activo.", options)
    for x in all_terms:
        if t in (norm(x["short_name"] or ""), norm(x["name"])):
            return x
    n = number_in(t)
    if n is not None:
        for x in all_terms:
            if x["sequence"] == n:
                return x
    raise Clarify(f'No encontré el periodo "{text}" en el año activo.', options)


# --- grades and sections --------------------------------------------------------------------


async def sections(conn: AsyncConnection) -> list[dict[str, Any]]:
    s = v.sections.c
    rows = await fetch_rows(
        conn,
        select(s.id, s.grade, s.grade_long, s.stage, s.section, s.name, s.shift).where(
            s.academic_year_status == "active", s.status == "active"
        ),
    )
    # The view has no grade ordinal: by stage, then the grade's number, then the letter.
    rows.sort(key=lambda r: (STAGES.get(r["stage"], 9), grade_position(r) or 99, r["section"]))
    return rows


STAGES = {"inicial": 0, "primaria": 1, "secundaria": 2}


def grade_position(row: dict[str, Any]) -> int | None:
    """1 for "1ro" / "Primero de Secundaria": the grade's number inside its stage."""
    return number_in(row["grade"] or "", roman=False) or number_in(row["grade_long"] or "")


@dataclass(frozen=True)
class Grade:
    grade_long: str
    stage: str | None
    position: int | None


def grades_of(all_sections: list[dict[str, Any]]) -> list[Grade]:
    seen: dict[str, Grade] = {}
    for s in all_sections:
        if s["grade_long"] not in seen:
            seen[s["grade_long"]] = Grade(s["grade_long"], s["stage"], grade_position(s))
    return list(seen.values())


def resolve_grade(all_sections: list[dict[str, Any]], text: str) -> Grade:
    """ "primero", "1ro", "1° de secundaria", "primero de primaria"."""
    grades = grades_of(all_sections)
    options = [g.grade_long for g in grades]
    t = norm(text)
    exact = [g for g in grades if norm(g.grade_long) == t]
    if exact:
        return exact[0]
    n = number_in(t, roman=False)
    candidates = [g for g in grades if n is not None and g.position == n]
    for stage in ("secundaria", "primaria", "inicial"):
        if stage in t:
            candidates = [g for g in candidates if g.stage and norm(g.stage) == stage]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise Clarify(f'"{text}" coincide con varios grados. ¿Cuál?',
                      [g.grade_long for g in candidates])  # fmt: skip
    raise Clarify(f'No encontré el grado "{text}" en el año activo.', options)


def resolve_section(
    all_sections: list[dict[str, Any]], text: str, grade: Grade | None = None
) -> dict[str, Any]:
    """ "A", "1A", "1ro A", "sección B", "primero B"."""
    pool = [s for s in all_sections if grade is None or s["grade_long"] == grade.grade_long]
    options = [f"{s['name']} ({s['grade_long']})" for s in all_sections]
    t = norm(text)
    for s in pool:
        if t == norm(s["name"] or ""):
            return s
    letters = [tok for tok in tokens(t) if len(tok) == 1 and tok.isalpha()]
    n = number_in(t, roman=False)
    candidates = [
        s for s in pool
        if letters and norm(s["section"]) == letters[-1]
        and (n is None or grade_position(s) == n)
    ]  # fmt: skip
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise Clarify(f'"{text}" coincide con varias secciones. ¿Cuál?',
                      [f"{s['name']} ({s['grade_long']})" for s in candidates])  # fmt: skip
    raise Clarify(f'No encontré la sección "{text}" en el año activo.', options)


# --- áreas ------------------------------------------------------------------------------------


async def areas(conn: AsyncConnection) -> list[dict[str, Any]]:
    c = v.competencies.c
    return await fetch_rows(
        conn,
        select(c.subject_code, c.subject_name, c.subject_order)
        .distinct()
        .order_by(c.subject_order, c.subject_code),
    )


def resolve_area(all_areas: list[dict[str, Any]], text: str) -> dict[str, Any]:
    """ "MAT", "matemática", "mate", "comu", "ciencias sociales"."""
    options = [a["subject_name"] for a in all_areas]
    t = norm(text)
    by_code = {norm(a["subject_code"]): a for a in all_areas}
    if t in by_code:
        return by_code[t]
    for a in all_areas:
        if t == norm(a["subject_name"]):
            return a
    alias = AREA_ALIASES.get(t)
    if alias and norm(alias) in by_code:
        return by_code[norm(alias)]
    candidates = [a for a in all_areas if len(t) >= 4 and t in norm(a["subject_name"])]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise Clarify(f'"{text}" coincide con varias áreas. ¿Cuál?',
                      [a["subject_name"] for a in candidates])  # fmt: skip
    raise Clarify(f'No encontré el área "{text}".', options)


# --- students ---------------------------------------------------------------------------------


async def resolve_student(conn: AsyncConnection, text: str) -> dict[str, Any]:
    """A student of the active year by name and surnames, in any order, accents ignored. Every
    word written must start a word of the student's name."""
    s = v.students.c
    rows = await fetch_rows(
        conn,
        select(
            s.student_id,
            s.full_name,
            s.given_name,
            s.preferred_name,
            s.paternal_surname,
            s.maternal_surname,
            s.section_id,
            s.section_name,
            s.grade_long,
            s.joined_on,
            s.left_on,
        )  # fmt: skip
        .where(s.academic_year_status == "active")
        .order_by(
            s.left_on.is_not(None),
            s.section_name,
            s.paternal_surname,
            s.maternal_surname,
            s.given_name,
        ),  # fmt: skip
    )
    wanted = [tok for tok in tokens(text) if len(tok) >= 2]
    if not wanted:
        raise Clarify("¿De qué alumno? Escribe su nombre o sus apellidos.", [])

    def matches(r: dict[str, Any]) -> bool:
        parts = tokens(
            " ".join(
                p or ""
                for p in (
                    r["given_name"],
                    r["preferred_name"],
                    r["paternal_surname"],
                    r["maternal_surname"],
                )  # fmt: skip
            )
        )
        return all(any(p.startswith(w) for p in parts) for w in wanted)

    found = [r for r in rows if matches(r)]
    unique: dict[Any, dict[str, Any]] = {}
    for r in found:  # one row per student: the current membership first
        unique.setdefault(r["student_id"], r)
    if len(unique) == 1:
        return next(iter(unique.values()))
    if len(unique) > 1:
        raise Clarify(f'Hay varios alumnos que coinciden con "{text}". ¿Cuál?',
                      [f"{r['full_name']} ({r['section_name']})" for r in unique.values()])  # fmt: skip
    raise Clarify(f'No encontré a ningún alumno "{text}" en el año activo.', [])


# --- the common filters ---------------------------------------------------------------------


@dataclass
class Scope:
    """The grade, section and área a question narrows to, and how to say it."""

    grade: Grade | None = None
    section: dict[str, Any] | None = None
    area: dict[str, Any] | None = None

    def where(self, view: Table) -> list[ColumnElement[bool]]:
        """Conditions on a chat_api view with grade_long, section_id and subject_code."""
        out: list[ColumnElement[bool]] = []
        if self.grade is not None:
            out.append(view.c.grade_long == self.grade.grade_long)
        if self.section is not None:
            out.append(view.c.section_id == self.section["id"])
        if self.area is not None:
            out.append(view.c.subject_code == self.area["subject_code"])
        return out

    def describe(self) -> str:
        parts: list[str] = []
        if self.section is not None:
            parts.append(f"{self.section['name']} ({self.section['grade_long']})")
        elif self.grade is not None:
            parts.append(self.grade.grade_long)
        if self.area is not None:
            parts.append(self.area["subject_name"])
        return ", ".join(parts) if parts else "todo el colegio"


async def resolve_scope(
    conn: AsyncConnection,
    grado: str | None = None,
    seccion: str | None = None,
    area: str | None = None,
) -> Scope:
    scope = Scope()
    if grado or seccion:
        all_sections = await sections(conn)
        if grado:
            scope.grade = resolve_grade(all_sections, grado)
        if seccion:
            scope.section = resolve_section(all_sections, seccion, scope.grade)
    if area:
        scope.area = resolve_area(await areas(conn), area)
    return scope
