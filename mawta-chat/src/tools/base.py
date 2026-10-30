"""What every tool shares: its declaration, the outcome it returns, and the way it asks the
director to choose when a parameter matches several things (or nothing)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast, override

from psycopg import AsyncConnection
from psycopg.rows import DictRow

# At most this many rows go to the model; the director's block always carries them all.
MAX_MODEL_ROWS = 60


@dataclass
class ToolOutcome:
    """result goes to the model; blocks go to the director as they are (built from the database,
    never from the model's text: the model does not retype numbers)."""

    result: dict[str, Any]
    blocks: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False


class Clarify(Exception):
    """A parameter matched several things, or none: the tool answers with the valid options and
    the model asks the director to choose (D003)."""

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
Run = Callable[[AsyncConnection[DictRow], Args], Awaitable[ToolOutcome]]


@dataclass(frozen=True)
class Param:
    description: str
    kind: str = "string"  # "string" or "integer"
    enum: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    status: str  # what the director sees while it runs
    params: dict[str, Param]
    run: Run

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
            if p.kind == "integer":
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


def rows_for_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The rows the model reads, capped, with how many there were."""
    out: dict[str, Any] = {"total_filas": len(rows), "filas": rows[:MAX_MODEL_ROWS]}
    if len(rows) > MAX_MODEL_ROWS:
        out["aviso"] = (
            f"Solo se muestran {MAX_MODEL_ROWS} de {len(rows)} filas al modelo; "
            "la directora ve la tabla completa."
        )
    return out
