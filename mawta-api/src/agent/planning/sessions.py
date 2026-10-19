"""Session outline proposals for the class dates without a session."""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from agent import InvalidAnswer, Prepared, Spec
from agent.llm import Tool
from agent.planning import (
    clean,
    decode,
    experience_id_of,
    strings_of,
    system,
    text_of,
)
from agent.planning.criteria import context_line, deref
from errors import AppError
from repo import planning as repo
from repo import planning_outline as outline
from repo import planning_plan as plan_repo


@dataclass
class _State:
    experience_id: UUID


SESSIONS_TOOL = Tool(
    name="proponer_sesiones",
    description="Registra el esquema ligero de sesiones propuesto para las fechas de clase sin "
    "sesión.",
    properties={
        "sessions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Una de las fechas vacías, YYYY-MM-DD.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Título corto de la sesión (máximo 8 palabras).",
                    },
                    "topics": {
                        "type": "string",
                        "description": "Temas de la sesión, en una línea.",
                    },
                    "planned_evidence_id": {
                        "type": "string",
                        "description": "Id (uuid) de la evidencia que se recoge en esta sesión, "
                        "copiado de la lista de evidencias sin sesión; cadena vacía si la sesión "
                        "no lleva evidencia.",
                    },
                },
                "required": ["date", "title", "topics", "planned_evidence_id"],
            },
        },
    },
    required=["sessions"],
)

# Indexed by isoweekday() % 7: Sunday is 0.
WEEKDAYS = ("domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado")


def empty_dates(exp: dict) -> list[str]:
    """The experience's class dates without a session entry."""
    taken = {s["date"] for s in exp["sessions"]}
    return [d for d in exp["class_dates"] if d not in taken]


async def prepare(conn: AsyncConnection, gen: dict) -> Prepared:
    exp_id = experience_id_of(gen)
    exp = await repo.get_experience(conn, exp_id)
    empty = empty_dates(exp)
    if not empty:
        return Prepared(result={"session_dates": []})

    cur = await plan_repo.get_curriculum(conn, gen["class_id"])
    performances = {p["id"]: p["text"] for c in cur["competencies"] for p in c["performances"]}

    lines = [
        f"Experiencia: {exp['title']} (del {exp['starts_on']} al {exp['ends_on']})",
        f"Situación: {deref(exp['situation_text'])}",
        context_line(exp["context_text"]),
        "Criterios de la experiencia, con su desempeño cuando lo tienen (fuente de los temas):",
    ]
    for c in exp["criteria"]:
        line = f"- {c['description']}"
        if c["performance_id"] is not None and performances.get(c["performance_id"]):
            line += f" — desempeño: {performances[c['performance_id']]}"
        lines.append(line)
    if exp["sessions"]:
        lines += ["", "Sesiones que ya existen (no las cambies):"]
        lines += [f"- {s['date']}: {s['title']}" for s in exp["sessions"]]
    unplaced = [e for e in exp["evidences"] if e["session_date"] is None]
    if unplaced:
        lines += ["", "Evidencias sin sesión (ubícalas):"]
        lines += [f"- id={e['id']} {e['name']} ({e['kind']})" for e in unplaced]
    lines += ["", "Fechas de clase vacías (propón una sesión para cada una):"]
    for d in empty:
        weekday = WEEKDAYS[date.fromisoformat(d).isoweekday() % 7]
        lines.append(f"- {d} ({weekday})")
    return Prepared(
        spec=Spec(
            system=system("sessions", ""),
            prompt="\n".join(lines) + "\n",
            tool=SESSIONS_TOOL,
            max_tokens=6000,
        ),
        state=_State(exp_id),
    )


async def apply(conn: AsyncConnection, gen: dict, prepared: Prepared, answer: Any) -> Any:
    st: _State = prepared.state
    a = decode(answer)
    raw_items = a.get("sessions") or []
    if not isinstance(raw_items, list) or not all(isinstance(s, dict) for s in raw_items):
        raise InvalidAnswer("la respuesta no tiene el formato de la herramienta: sessions")
    items = [
        (
            text_of(s.get("date")),
            text_of(s.get("title")),
            text_of(s.get("topics")),
            text_of(s.get("planned_evidence_id")),
        )
        for s in raw_items
    ]
    _ = strings_of

    exp = await repo.get_experience(conn, st.experience_id)
    empty = {d: True for d in empty_dates(exp)}
    unplaced = {e["id"]: True for e in exp["evidences"] if e["session_date"] is None}
    dates: list[str] = []
    reasons: list[str] = []
    for i, (raw_date, raw_title, raw_topics, raw_evidence) in enumerate(items, start=1):
        day_text, title = raw_date.strip(), clean(raw_title)
        if not empty.get(day_text):
            reasons.append(f'sesión {i}: "{day_text}" no es una de las fechas vacías')
            continue
        if not title:
            reasons.append(f"sesión {i}: título vacío")
            continue
        topics = clean(raw_topics)
        evidence_id: UUID | None = None
        try:
            candidate = UUID(raw_evidence.strip())
        except ValueError:
            candidate = None
        if candidate is not None and unplaced.get(candidate):
            evidence_id = candidate
        try:
            inserted = await outline.propose_session_entry(
                conn,
                st.experience_id,
                date.fromisoformat(day_text),
                {
                    "title": title,
                    "topics": topics or None,
                    "planned_evidence_id": evidence_id,
                },
            )
        except AppError as exc:
            if exc.status < 500:
                reasons.append(f"sesión {i}: {exc.message}")
                continue
            raise
        if not inserted:
            continue  # the teacher filled this date meanwhile
        dates.append(day_text)
        empty[day_text] = False
        if evidence_id is not None:
            unplaced[evidence_id] = False
    if not dates:
        if not reasons:
            raise InvalidAnswer("la lista sessions vino vacía, pero hay fechas de clase sin sesión")
        raise InvalidAnswer("ninguna sesión se pudo usar: " + "; ".join(reasons))
    return {"session_dates": dates}
