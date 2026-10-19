"""Evidence proposals for the criteria no evidence observes yet."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from mawta_api import domain
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
from mawta_api.agent.planning.criteria import context_line, deref
from mawta_api.errors import AppError
from mawta_api.repo import planning as repo


@dataclass
class _State:
    experience_id: UUID


EVIDENCES_TOOL = Tool(
    name="proponer_evidencias",
    description="Registra las evidencias propuestas para observar los criterios que todavía no "
    "tienen evidencia.",
    properties={
        "evidences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Nombre corto y concreto de la evidencia.",
                    },
                    "kind": {
                        "type": "string",
                        "enum": [domain.EVIDENCE_PRODUCCION, domain.EVIDENCE_ACTUACION],
                    },
                    "criterion_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ids de los criterios que observa.",
                    },
                },
                "required": ["name", "kind", "criterion_ids"],
            },
        },
    },
    required=["evidences"],
)


def observed_criteria(exp: dict) -> set[UUID]:
    """The criteria some evidence of the experience already observes, pending proposals included."""
    return {cid for e in exp["evidences"] for cid in e["criterion_ids"]}


async def prepare(conn: AsyncConnection, gen: dict) -> Prepared:
    exp_id = experience_id_of(gen)
    exp = await repo.get_experience(conn, exp_id)
    if not exp["criteria"]:
        raise unprocessable(
            "no_criteria",
            "Primero define los criterios: las evidencias se proponen a partir de ellos.",
        )
    observed = observed_criteria(exp)
    if all(c["id"] in observed for c in exp["criteria"]):
        return Prepared(result={"evidence_ids": []})

    competency = {c["id"]: c["name"] for c in exp["competencies"]}
    lines = [
        f"Experiencia: {exp['title']}",
        f"Situación: {deref(exp['situation_text'])}",
        context_line(exp["context_text"]),
        "Criterios de la experiencia:",
    ]
    for c in exp["criteria"]:
        mark = "ya tiene evidencia" if c["id"] in observed else "SIN EVIDENCIA"
        lines.append(
            f"- id={c['id']} [{competency.get(c['competency_id'], '')}] {c['description']} ({mark})"
        )
    if exp["evidences"]:
        lines += ["", "Evidencias que ya existen (no las repitas):"]
        lines += [f"- {e['name']} ({e['kind']})" for e in exp["evidences"]]
    return Prepared(
        spec=Spec(
            system=system("evidences", ""),
            prompt="\n".join(lines) + "\n",
            tool=EVIDENCES_TOOL,
            max_tokens=3000,
        ),
        state=_State(exp_id),
    )


async def apply(conn: AsyncConnection, gen: dict, prepared: Prepared, answer: Any) -> Any:
    st: _State = prepared.state
    a = decode(answer)
    raw_items = a.get("evidences") or []
    if not isinstance(raw_items, list) or not all(isinstance(e, dict) for e in raw_items):
        raise InvalidAnswer("la respuesta no tiene el formato de la herramienta: evidences")
    items = [
        (text_of(e.get("name")), text_of(e.get("kind")), strings_of(e.get("criterion_ids")))
        for e in raw_items
    ]

    exp = await repo.get_experience(conn, st.experience_id)
    in_experience = {c["id"] for c in exp["criteria"]}
    observed = observed_criteria(exp)
    seen_name = {clean(e["name"]).lower() for e in exp["evidences"]}
    ids: list[UUID] = []
    reasons: list[str] = []
    for i, (raw_name, raw_kind, raw_criteria) in enumerate(items, start=1):
        name, kind = clean(raw_name), raw_kind.strip()
        if not name or name.lower() in seen_name:
            reasons.append(f"evidencia {i}: nombre vacío o repetido")
            continue
        if not domain.is_evidence_kind(kind):
            reasons.append(f"evidencia {i}: kind debe ser produccion o actuacion")
            continue
        criterion_ids: list[UUID] = []
        fills_gap = False
        seen: set[UUID] = set()
        for s in raw_criteria:
            try:
                cid = UUID(s.strip())
            except ValueError:
                continue
            if cid not in in_experience or cid in seen:
                continue
            seen.add(cid)
            criterion_ids.append(cid)
            if cid not in observed:
                fills_gap = True
        if not criterion_ids or not fills_gap:
            reasons.append(
                f"evidencia {i}: debe observar al menos un criterio SIN EVIDENCIA de la lista"
            )
            continue
        try:
            new_id = await repo.propose_evidence(
                conn,
                st.experience_id,
                {"name": name, "kind": kind, "criterion_ids": criterion_ids},
            )
        except AppError as exc:
            if exc.status < 500:
                reasons.append(f"evidencia {i}: {exc.message}")
                continue
            raise
        ids.append(new_id)
        seen_name.add(name.lower())
        observed.update(criterion_ids)
    if not ids:
        if not reasons:
            raise InvalidAnswer("la lista evidences vino vacía, pero hay criterios sin evidencia")
        raise InvalidAnswer("ninguna evidencia se pudo usar: " + "; ".join(reasons))
    return {"evidence_ids": ids}
