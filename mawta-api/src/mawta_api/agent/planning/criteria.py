"""Criteria proposals for the capabilities of one competency that have none. The agent fills gaps
only."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from mawta_api.agent import InvalidAnswer, Prepared, Spec
from mawta_api.agent.llm import Tool
from mawta_api.agent.planning import (
    clean,
    decode,
    experience_id_of,
    strings_of,
    system,
    text_of,
    unprocessable,
)
from mawta_api.errors import AppError
from mawta_api.repo import planning as repo
from mawta_api.repo import planning_plan as plan_repo


@dataclass
class _State:
    experience_id: UUID
    competency_id: UUID
    capabilities: set[UUID]


CRITERIA_TOOL = Tool(
    name="proponer_criterios",
    description="Registra los criterios de evaluación propuestos para las capacidades que todavía "
    "no tienen criterio.",
    properties={
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "El criterio: una oración en tercera persona que empieza "
                        "con un verbo en presente.",
                    },
                    "capability_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ids de las capacidades que mira el criterio.",
                    },
                },
                "required": ["description", "capability_ids"],
            },
        },
    },
    required=["criteria"],
)


def covered_capabilities(exp: dict, competency_id: UUID) -> set[UUID]:
    """The capabilities of a competency that some criterion of the experience already looks at,
    pending proposals included: the agent fills gaps only."""
    return {
        cap
        for c in exp["criteria"]
        if c["competency_id"] == competency_id
        for cap in c["capability_ids"]
    }


def existing_criteria(exp: dict, competency_id: UUID) -> list[str]:
    return [c["description"] for c in exp["criteria"] if c["competency_id"] == competency_id]


def cycle_label(cycle: str | None) -> str:
    """ "ciclo_vi" -> "ciclo VI"."""
    if cycle is None:
        return "ciclo"
    if not cycle.startswith("ciclo_"):
        return cycle
    return "ciclo " + cycle.removeprefix("ciclo_").upper()


def deref(text: str | None) -> str:
    return "(sin situación redactada)" if text is None else text


def context_line(text: str | None) -> str:
    """The teacher's event or context for a planning prompt. When there is none it says so
    outright, so the agent has no room to invent an event."""
    if text is not None and text.strip():
        return "Contexto del docente: " + text.strip() + "\n"
    return (
        "Contexto del docente: ninguno. No incluyas ningún evento, feria, aniversario, "
        "campaña ni actividad social.\n"
    )


async def prepare(conn: AsyncConnection, gen: dict) -> Prepared:
    exp_id = experience_id_of(gen)
    try:
        competency_id = UUID((gen["input"] or {})["competency_id"])
    except (KeyError, ValueError, TypeError):
        raise unprocessable("bad_request", "el pedido de criterios no es válido") from None
    exp = await repo.get_experience(conn, exp_id)
    comp_name = next((c["name"] for c in exp["competencies"] if c["id"] == competency_id), "")
    if not comp_name:
        raise unprocessable(
            "competency_not_in_experience", "esa competencia no está en esta experiencia"
        )

    cur = await plan_repo.get_curriculum(conn, gen["class_id"])
    comp = next((c for c in cur["competencies"] if c["id"] == competency_id), None)
    if comp is None or comp["standard"] is None:
        raise unprocessable(
            "no_standard",
            "Esta competencia no tiene estándar cargado para el ciclo; escribe los criterios a mano.",
        )

    covered = covered_capabilities(exp, competency_id)
    state = _State(exp_id, competency_id, {cap["id"] for cap in comp["capabilities"]})
    gaps = [cap for cap in comp["capabilities"] if cap["id"] not in covered]
    if not gaps:
        return Prepared(result={"criteria_ids": []})

    grade = cur["grade"]
    lines = [
        f"Experiencia: {exp['title']}",
        f"Situación: {deref(exp['situation_text'])}",
        context_line(exp["context_text"]).rstrip("\n"),
        f"Competencia: {comp_name}",
        "",
        "Capacidades:",
    ]
    for cap in comp["capabilities"]:
        mark = "ya tiene criterio" if cap["id"] in covered else "SIN CRITERIO"
        lines.append(f"- id={cap['id']} {cap['name']} ({mark})")
    lines += [
        "",
        f"Estándar de aprendizaje, nivel esperado al final del {cycle_label(grade['cycle'])}:",
        comp["standard"]["text"],
    ]
    if comp["performances"]:
        if comp["performances"][0]["en_proceso"]:
            lines += ["", f"El grado {grade['code']} está en proceso hacia ese nivel."]
        else:
            lines += ["", f"El grado {grade['code']} alcanza ese nivel."]
        lines += [
            "",
            f"Desempeños del grado {grade['code']} (solo para calibrar la exigencia del grado; "
            "no los cites):",
        ]
        lines += [f"- {p['text']}" for p in comp["performances"]]
    existing = existing_criteria(exp, competency_id)
    if existing:
        lines += ["", "Criterios que ya existen para esta competencia (no los repitas):"]
        lines += [f"- {d}" for d in existing]
    return Prepared(
        spec=Spec(
            system=system("criteria", ""),
            prompt="\n".join(lines) + "\n",
            tool=CRITERIA_TOOL,
            max_tokens=4000,
        ),
        state=state,
    )


async def apply(conn: AsyncConnection, gen: dict, prepared: Prepared, answer: Any) -> Any:
    st: _State = prepared.state
    a = decode(answer)
    raw_criteria = a.get("criteria") or []
    if not isinstance(raw_criteria, list) or not all(isinstance(c, dict) for c in raw_criteria):
        raise InvalidAnswer("la respuesta no tiene el formato de la herramienta: criteria")
    items = [
        (text_of(c.get("description")), strings_of(c.get("capability_ids"))) for c in raw_criteria
    ]

    # Coverage is re-read inside this transaction: the teacher may have written criteria while
    # the model was thinking.
    exp = await repo.get_experience(conn, st.experience_id)
    covered = covered_capabilities(exp, st.competency_id)
    seen_text = {clean(d).lower() for d in existing_criteria(exp, st.competency_id)}
    ids: list[UUID] = []
    reasons: list[str] = []
    for i, (raw_description, raw_caps) in enumerate(items, start=1):
        description = clean(raw_description)
        if not description or description.lower() in seen_text:
            reasons.append(f"criterio {i}: descripción vacía o repetida")
            continue
        capability_ids: list[UUID] = []
        fills_gap = False
        for s in raw_caps:
            try:
                cid = UUID(s.strip())
            except ValueError:
                continue
            if cid not in st.capabilities:
                continue
            capability_ids.append(cid)
            if cid not in covered:
                fills_gap = True
        if not capability_ids or not fills_gap:
            reasons.append(
                f"criterio {i}: debe mirar al menos una capacidad SIN CRITERIO de la lista"
            )
            continue
        try:
            new_id = await repo.propose_criterion(
                conn,
                st.experience_id,
                {
                    "competency_id": st.competency_id,
                    "description": description,
                    "capability_ids": capability_ids,
                },
            )
        except AppError as exc:
            if exc.status < 500:
                reasons.append(f"criterio {i}: {exc.message}")
                continue
            raise
        ids.append(new_id)
        seen_text.add(description.lower())
        covered.update(capability_ids)
    if not ids and items:
        raise InvalidAnswer("ningún criterio se pudo usar: " + "; ".join(reasons))
    if not ids:
        raise InvalidAnswer("la lista criteria vino vacía, pero hay capacidades sin criterio")
    return {"criteria_ids": ids}


_ = plan_repo
