"""Mawta's planning agent, the first agent of the multi-agent system (port of agent/planning).

It proposes, from a teacher's idea and the loaded CNEB curriculum, a learning experience, its
evaluation criteria, its planned evidences and a light session outline (contract
docs/api-planificacion.md, "Generate with Mawta").

It never decides: an experience proposal is returned for review and not saved; criteria,
evidences and sessions are saved pending (proposed_by = mawta) until the teacher accepts or edits
them. It only fills gaps, only cites what the database holds, never suggests achievement levels,
and receives no student data.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from agent import InvalidAnswer, Prepared
from agent.llm import Block
from errors import AppError

NAME = "planning"  # the agent_generations.agent value of this agent

# What the planning agent generates (agent_generations.kind).
KIND_EXPERIENCE = "experience"
KIND_CRITERIA = "criteria"
KIND_EVIDENCES = "evidences"
KIND_SESSIONS = "sessions"

# Changes whenever the instructions in prompts/ change, so a generation can be traced to the prompt
# that produced it.
PROMPT_VERSION = "planning-2026-10-13.1"

_PROMPTS = Path(__file__).parent / "prompts"


def prompt(name: str) -> str:
    return (_PROMPTS / f"{name}.md").read_text()


def unprocessable(code: str, message: str) -> AppError:
    return AppError(422, code, message)


def target_key(kind: str, class_id: UUID, experience_id: UUID | None, competency_id: UUID) -> str:
    """Identifies what a generation works on, so only one generation per target runs at a time
    (agent_generations_target_key)."""
    if kind == KIND_EXPERIENCE:
        return f"planning:class:{class_id}:experience"
    if kind == KIND_CRITERIA:
        return f"planning:exp:{experience_id}:criteria:{competency_id}"
    return f"planning:exp:{experience_id}:{kind}"


def system(task: str, context: str) -> list[Block]:
    """The stable, cacheable instructions of a call: the common rules, the task, and the class
    context that repeats across calls."""
    blocks = [Block(prompt("common") + "\n\n" + prompt(task), cache=context == "")]
    if context:
        blocks.append(Block(context, cache=True))
    return blocks


def decode(answer: Any, expected: type = dict) -> Any:
    """A malformed answer is invalid, which earns the model one repair attempt."""
    if not isinstance(answer, expected):
        raise InvalidAnswer("la respuesta no tiene el formato de la herramienta: wrong JSON type")
    return answer


def experience_id_of(gen: dict[str, Any]) -> UUID:
    if gen["experience_id"] is None:
        raise unprocessable("bad_request", "esta generación necesita una experiencia")
    return gen["experience_id"]


def clean(text: str) -> str:
    """Trim a model string and collapse inner whitespace."""
    return " ".join(text.split())


def text_of(value: Any) -> str:
    """A model string field; null counts as empty, any other type is an unusable answer."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidAnswer("la respuesta no tiene el formato de la herramienta: expected a string")
    return value


def strings_of(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise InvalidAnswer(
            "la respuesta no tiene el formato de la herramienta: expected a list of strings"
        )
    return value


class PlanningAgent:
    name = NAME
    prompt_version = PROMPT_VERSION

    async def prepare(self, conn: AsyncConnection[DictRow], gen: dict[str, Any]) -> Prepared:
        from agent.planning import criteria, evidences, experience, sessions

        handlers = {
            KIND_EXPERIENCE: experience.prepare,
            KIND_CRITERIA: criteria.prepare,
            KIND_EVIDENCES: evidences.prepare,
            KIND_SESSIONS: sessions.prepare,
        }
        handler = handlers.get(gen["kind"])
        if handler is None:
            raise unprocessable("unknown_kind", "Mawta no sabe generar eso.")
        return await handler(conn, gen)

    async def apply(
        self, conn: AsyncConnection[DictRow], gen: dict[str, Any], prepared: Prepared, answer: Any
    ) -> Any:
        from agent.planning import criteria, evidences, experience, sessions

        handlers = {
            KIND_EXPERIENCE: experience.apply,
            KIND_CRITERIA: criteria.apply,
            KIND_EVIDENCES: evidences.apply,
            KIND_SESSIONS: sessions.apply,
        }
        handler = handlers.get(gen["kind"])
        if handler is None:
            raise unprocessable("unknown_kind", "Mawta no sabe generar eso.")
        return await handler(conn, gen, prepared, answer)
