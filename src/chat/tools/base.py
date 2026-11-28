"""What every tool shares: its declaration, the outcome it returns, and the way it asks the
director to choose when a parameter matches several things (or nothing)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast, override

from sqlalchemy import Executable
from sqlalchemy.ext.asyncio import AsyncConnection

# At most this many rows go to the model; the director's block always carries them all.
MAX_MODEL_ROWS = 60


@dataclass
class ToolOutcome:
    """result goes to the model; blocks go to the director as they are (built from the database,
    never from the model's text: the model does not retype numbers). A tool fills blocks only
    when the model asked to show them (mostrar_bloque)."""

    result: dict[str, Any]
    blocks: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False


class Clarify(Exception):
    """A parameter matched several things, or none: the tool answers with the valid options and
    the model asks the director to choose."""

    message: str
    options: list[str]

    def __init__(self, message: str, options: list[str]) -> None:
        super().__init__(message)
        self.message = message
        self.options = options

    def outcome(self) -> ToolOutcome:
        return ToolOutcome(
            result={"necesita_aclaracion": self.message, "opciones": self.options[:MAX_MODEL_ROWS]}
        )


class NoData(Clarify):
    """Nothing to choose from: the data does not exist yet (no period has levels). Caught like
    Clarify, but the model is told there is no data instead of being asked to ask."""

    def __init__(self, message: str) -> None:
        super().__init__(message, [])

    @override
    def outcome(self) -> ToolOutcome:
        return ToolOutcome(result={"sin_datos": self.message})


Args = dict[str, Any]
Run = Callable[[AsyncConnection, Args], Awaitable[ToolOutcome]]


@dataclass(frozen=True)
class Param:
    description: str
    kind: str = "string"  # "string", "integer" or "boolean"
    enum: tuple[str, ...] = ()


# The parameter every data tool declares: the model reads data without showing it (to look into
# something, cross two results or answer one figure in text) and shows a chart or table only when
# it makes the answer clearer.
SHOW_BLOCK = "mostrar_bloque"
MOSTRAR_BLOQUE = Param(
    "true to show the director this result's chart or table below your answer; false (the "
    "default) to only read the data. Show it when it makes the answer clearer: an overview by "
    "área or section, a long list or history, or when the director asks to see it. Leave it "
    "false for intermediate steps and for questions answered with a figure or two.",
    kind="boolean",
)


def shown(args: Args, *blocks: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The blocks a tool returns: none unless the model asked to show them, and never an empty
    one (a block is None when the tool had no rows to show)."""
    if not args.get(SHOW_BLOCK):
        return []
    return [b for b in blocks if b is not None]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    status: str  # what the director sees while it runs
    params: dict[str, Param]
    run: Run
    # What it lets the chat look up, in Spanish, for the list in the system prompt. Empty for the
    # tools that look nothing up (fuera_de_alcance, sin_herramienta).
    topic: str = ""

    @property
    def shows_blocks(self) -> bool:
        return SHOW_BLOCK in self.params

    def spec(self) -> dict[str, Any]:
        """The OpenAI-compatible function declaration. Every parameter is optional."""
        properties: dict[str, Any] = {}
        for name, p in self.params.items():
            prop: dict[str, Any] = {"type": p.kind, "description": p.description}
            if p.enum:
                prop["enum"] = list(p.enum)
            properties[name] = prop
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "additionalProperties": False,
                },
            },
        }

    def check(self, tool_input: Any) -> Args:
        """The model's arguments, validated against the declaration. Raises ValueError with a
        message the model can act on."""
        if tool_input is None:
            return {}
        if not isinstance(tool_input, dict):
            raise ValueError("the arguments must be a JSON object")
        args: Args = {}
        for key, value in cast(dict[str, Any], tool_input).items():
            if key not in self.params:
                raise ValueError(f"unknown parameter {key!r}; use only {sorted(self.params)}")
            if value is None or value == "":
                continue
            p = self.params[str(key)]
            if p.kind == "boolean":
                if isinstance(value, str) and value.strip().lower() in ("true", "false"):
                    value = value.strip().lower() == "true"
                if not isinstance(value, bool):
                    raise ValueError(f"{key} must be true or false")
            elif p.kind == "integer":
                if isinstance(value, bool) or not isinstance(value, int | str):
                    raise ValueError(f"{key} must be an integer")
                try:
                    value = int(value)
                except ValueError:
                    raise ValueError(f"{key} must be an integer") from None
            elif not isinstance(value, str):
                raise ValueError(f"{key} must be text")
            if p.enum and value not in p.enum:
                raise ValueError(f"{key} must be one of {list(p.enum)}")
            args[str(key)] = value
        return args


async def fetch_rows(conn: AsyncConnection, stmt: Executable) -> list[dict[str, Any]]:
    """The rows of a query on chat_api, as plain dicts the tools can extend."""
    return [dict(r) for r in (await conn.execute(stmt)).mappings().all()]


def students_by_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Distinct students per educational stage (primaria, secundaria) and per section, in the
    rows' order: the breakdowns the director asks for next, stated by the tool so the model never
    counts rows itself. A breakdown with a single group is left out."""
    stages: dict[str, set[Any]] = {}
    sections: dict[str, set[Any]] = {}
    for r in rows:
        stages.setdefault(r["stage"] or "sin nivel educativo", set()).add(r["student_id"])
        sections.setdefault(r["section_name"], set()).add(r["student_id"])
    out: dict[str, Any] = {}
    if len(stages) > 1:
        out["alumnos_por_nivel_educativo"] = {k: len(v) for k, v in stages.items()}
    if len(sections) > 1:
        out["alumnos_por_seccion"] = {k: len(v) for k, v in sections.items()}
    return out


def rows_for_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The rows the model reads, capped, with how many there were."""
    out: dict[str, Any] = {"total_filas": len(rows), "filas": rows[:MAX_MODEL_ROWS]}
    if len(rows) > MAX_MODEL_ROWS:
        out["aviso"] = (
            f"Solo se muestran {MAX_MODEL_ROWS} de {len(rows)} filas al modelo; "
            "la tabla completa se muestra al director solo si mostrar_bloque=true."
        )
    return out
