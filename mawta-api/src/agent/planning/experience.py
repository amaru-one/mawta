"""The experience proposal: shown for review, never saved by the agent (the teacher saves it with
POST /classes/{id}/experiences)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from agent import InvalidAnswer, Prepared, Spec
from agent.llm import Tool
from agent.planning import (
    clean,
    decode,
    strings_of,
    system,
    text_of,
    unprocessable,
)
from repo import planning_plan as plan_repo


@dataclass
class _State:
    offered: set[UUID]
    chosen: list[UUID]
    term: plan_repo.PlanTerm


EXPERIENCE_TOOL = Tool(
    name="proponer_experiencia",
    description="Registra la propuesta de experiencia de aprendizaje para la revisión del docente.",
    properties={
        "title": {
            "type": "string",
            "description": "Título corto de la experiencia (máximo 8 palabras).",
        },
        "situation_text": {
            "type": "string",
            "description": "Situación significativa de 3 a 6 oraciones, con una o dos preguntas "
            "retadoras al final.",
        },
        "competency_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Ids de las competencias del área que trabaja la experiencia.",
        },
        "starts_on": {
            "type": "string",
            "description": "Primer día, YYYY-MM-DD, dentro de una ventana libre.",
        },
        "ends_on": {
            "type": "string",
            "description": "Último día, YYYY-MM-DD, dentro de la misma ventana libre.",
        },
    },
    required=["title", "situation_text", "competency_ids", "starts_on", "ends_on"],
)


def _status_text(status: str) -> str:
    return {
        "toca": "toca este trimestre",
        "planificada": "ya planificada en este trimestre",
    }.get(status, "puede esperar")


async def prepare(conn: AsyncConnection, gen: dict) -> Prepared:
    inp = gen["input"] or {}
    try:
        term_id = UUID(inp["term_id"]) if inp.get("term_id") else None
        chosen = [UUID(s) for s in inp.get("competency_ids") or []]
        idea_text = inp.get("idea_text") or ""
        context_text = inp.get("context_text") or ""
        if not all(isinstance(v, str) for v in (idea_text, context_text)):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise unprocessable("bad_request", "el pedido de propuesta no es válido") from None

    cur = await plan_repo.get_curriculum(conn, gen["class_id"])
    term = await plan_repo.resolve_plan_term(
        conn, gen["class_id"], term_id or None, datetime.now().date()
    )
    plan = await plan_repo.get_plan(conn, gen["class_id"], term)
    windows = await usable_windows(conn, gen["class_id"], term)
    if not windows:
        raise unprocessable(
            "no_free_weeks", "No quedan semanas libres en este periodo para una experiencia nueva."
        )

    offered = {c["id"] for c in cur["competencies"]}
    for cid in chosen:
        if cid not in offered:
            raise unprocessable(
                "competency_not_in_subject", "esa competencia no es del área de esta clase"
            )
    status = {c["id"]: c["status"] for c in plan["competencies"]}

    ctx = [f'<curriculo grado="{cur["grade"]["code"]}">']
    for c in cur["competencies"]:
        ctx.append(f"Competencia id={c['id']}: {c['name']}")
        ctx += [f"  - Capacidad: {cap['name']}" for cap in c["capabilities"]]
        ctx += [f"  - Desempeño del grado: {p['text']}" for p in c["performances"]]
    ctx.append("</curriculo>")

    pr = [
        f"Periodo: {term.name}, del {term.public()['starts_on']} al {term.public()['ends_on']}.",
        "",
    ]
    pr.append("Ventanas libres (sin otra experiencia), con sus días de clase:")
    pr += [f"- del {w.starts_on} al {w.ends_on}: {w.class_dates} días de clase" for w in windows]
    if plan["non_teaching_days"]:
        pr += ["", "Días sin clases (feriados, vacaciones y días de gestión):"]
        for n in plan["non_teaching_days"]:
            label = n["label"] if n["label"] is not None else n["kind"]
            if n["from"] == n["to"]:
                pr.append(f"- {n['from']}: {label}")
            else:
                pr.append(f"- del {n['from']} al {n['to']}: {label}")
    pr += ["", "Seguimiento de competencias en el año:"]
    pr += [
        f"- id={c['id']} {c['name']}: {_status_text(status.get(c['id'], ''))}"
        for c in cur["competencies"]
    ]
    if chosen:
        pr += ["", "El docente eligió estas competencias (usa exactamente estas): "
               + ", ".join(str(i) for i in chosen)]  # fmt: skip
    else:
        pr += ["", "El docente no eligió competencias: elige tú entre 1 y 3 del área."]
    pr += ["", f"<idea_del_docente>\n{idea_text.strip()}\n</idea_del_docente>"]
    if context_text.strip():
        pr += ["", f"<contexto_del_docente>\n{context_text.strip()}\n</contexto_del_docente>"]
    else:
        pr += [
            "",
            "Contexto del docente: ninguno. No incluyas ningún evento, feria, aniversario, "
            "campaña ni actividad social.",
        ]
    return Prepared(
        spec=Spec(
            system=system("experience", "\n".join(ctx)),
            prompt="\n".join(pr) + "\n",
            tool=EXPERIENCE_TOOL,
            max_tokens=2500,
        ),
        state=_State(offered=offered, chosen=chosen, term=term),
    )


async def apply(conn: AsyncConnection, gen: dict, prepared: Prepared, answer: Any) -> Any:
    st: _State = prepared.state
    a = decode(answer)
    title = clean(text_of(a.get("title")))
    situation = text_of(a.get("situation_text")).strip()
    competency_ids = strings_of(a.get("competency_ids"))
    starts_on, ends_on = text_of(a.get("starts_on")), text_of(a.get("ends_on"))
    if not title or not situation:
        raise InvalidAnswer("title y situation_text son obligatorios y no pueden ir vacíos")

    competencies = list(st.chosen)
    if not competencies:
        seen: set[UUID] = set()
        for s in competency_ids:
            try:
                cid = UUID(s.strip())
            except ValueError:
                continue
            if cid not in st.offered or cid in seen:
                continue
            seen.add(cid)
            competencies.append(cid)
        if not competencies:
            raise InvalidAnswer(
                "competency_ids debe tener al menos un id de competencia de la lista del currículo"
            )

    try:
        start, end = date.fromisoformat(starts_on.strip()), date.fromisoformat(ends_on.strip())
    except ValueError:
        raise InvalidAnswer("starts_on y ends_on deben ser fechas YYYY-MM-DD") from None

    windows = await usable_windows(conn, gen["class_id"], st.term)
    fitted = fit_dates(windows, start, end)
    if fitted is None:
        raise unprocessable(
            "no_free_weeks", "No quedan semanas libres en este periodo para una experiencia nueva."
        )
    start, end = fitted
    return {
        "proposal": {
            "title": title,
            "situation_text": situation,
            "competency_ids": competencies,
            "starts_on": start.isoformat(),
            "ends_on": end.isoformat(),
        }
    }


@dataclass
class Window:
    starts_on: str
    ends_on: str
    class_dates: int
    from_: date
    to: date


async def usable_windows(
    conn: AsyncConnection, class_id: UUID, term: plan_repo.PlanTerm
) -> list[Window]:
    """The term's free stretches that hold at least one class date: an experience in a stretch
    without classes could not be taught."""
    out = []
    for w in await plan_repo.free_windows(conn, class_id, term):
        if w["class_dates"] == 0:
            continue
        out.append(
            Window(
                w["starts_on"],
                w["ends_on"],
                w["class_dates"],
                date.fromisoformat(w["starts_on"]),
                date.fromisoformat(w["ends_on"]),
            )
        )
    return out


def fit_dates(windows: list[Window], start: date, end: date) -> tuple[date, date] | None:
    """Keep the model's dates when they lie inside one free window, and otherwise move them to the
    nearest window, keeping the requested length as far as the window allows. The model picks; the
    server guarantees the proposal can actually be saved (no overlap, inside the term)."""
    if not windows:
        return None
    for w in windows:
        if start >= w.from_ and end <= w.to and end >= start:
            return start, end
    days = (end - start).days + 1
    if days < 1 or days > 60:
        days = 14
    best = windows[0]
    best_dist = _distance(start, best)
    for w in windows[1:]:
        if (d := _distance(start, w)) < best_dist:
            best, best_dist = w, d
    # Stay as close to the requested dates as the window allows: a window before them is used
    # from its end backwards, one after them from its start, one holding the start from that start.
    one = timedelta(days=1)
    if start > best.to:
        e = best.to
        s = e - one * (days - 1)
        if s < best.from_:
            s = best.from_
    elif start < best.from_:
        s = best.from_
        e = s + one * (days - 1)
    else:
        s = start
        e = s + one * (days - 1)
    if e > best.to:
        e = best.to
    return s, e


def _distance(d: date, w: Window) -> float:
    """How far a date is from a window, in days (0 inside it)."""
    if d < w.from_:
        return (w.from_ - d).days
    if d > w.to:
        return (d - w.to).days
    return 0
