"""The chat's tools. Each reads only chat_api views, inside the director's
chat transaction (role mawta_chat, which can read nothing else), and applies the glossary's
definitions in its own query.

A tool returns two things: the result for the model, and the blocks the director may see (built
from the database, never from the model's text: the model does not retype numbers). A data tool
shows its block only when the model passes mostrar_bloque=true, so the model can read data
silently, chain several tools in one answer, and show a chart or table only where it helps.

To add a tool: write its module (a Tool with its params, run and topic), add it to REGISTRY, and
give it mostrar_bloque if it has a block to show. The system prompt lists every tool's topic, so
the chat learns what it can look up without editing the prompt.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from chat.tools import (
    compare_periods,
    competency_risk,
    levels_summary,
    promotion,
    school,
    scope,
    student_history,
    students_with_c,
)
from chat.tools.base import SHOW_BLOCK, Tool, ToolOutcome

__all__ = [
    "DATA_TOOLS",
    "SCOPE_TOOLS",
    "TOOLS",
    "TOOL_STATUS",
    "TOPICS",
    "ToolOutcome",
    "block_requested",
    "run_tool",
]

REGISTRY: dict[str, Tool] = {
    t.name: t
    for t in (
        school.TOOL,
        levels_summary.TOOL,
        compare_periods.TOOL,
        students_with_c.TOOL,
        competency_risk.TOOL,
        promotion.TOOL,
        student_history.TOOL,
        scope.OUT_OF_SCOPE_TOOL,
        scope.NO_TOOL_TOOL,
    )
}
# The two tools that only say what the chat does not answer, and the ones that read data.
SCOPE_TOOLS: frozenset[str] = frozenset({scope.OUT_OF_SCOPE_TOOL.name, scope.NO_TOOL_TOOL.name})
DATA_TOOLS: frozenset[str] = frozenset(REGISTRY) - SCOPE_TOOLS

TOOLS: list[dict[str, Any]] = [t.spec() for t in REGISTRY.values()]
TOOL_STATUS: dict[str, str] = {name: t.status for name, t in REGISTRY.items()}
# What the chat can look up, one line per data tool, for the system prompt.
TOPICS: dict[str, str] = {name: t.topic for name, t in REGISTRY.items() if t.topic}


def block_requested(tool_input: Any) -> bool:
    """Whether a call's arguments ask to show its block: only a literal true (or "true")."""
    if not isinstance(tool_input, dict):
        return False
    value: Any = tool_input.get(SHOW_BLOCK)  # pyright: ignore[reportUnknownMemberType]
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


async def run_tool(name: str, tool_input: Any, conn: AsyncConnection) -> ToolOutcome:
    tool = REGISTRY.get(name)
    if tool is None:
        return ToolOutcome(result={"error": f"unknown tool {name!r}"}, is_error=True)
    try:
        args = tool.check(tool_input)
    except ValueError as exc:
        return ToolOutcome(result={"error": str(exc)}, is_error=True)
    outcome = await tool.run(conn, args)
    answered = not outcome.is_error and not (
        {"sin_datos", "necesita_aclaracion"} & outcome.result.keys()
    )
    if tool.shows_blocks and answered:
        # The model writes its answer knowing whether the director sees the rows below it.
        outcome.result["bloque_mostrado"] = bool(outcome.blocks)
    return outcome
