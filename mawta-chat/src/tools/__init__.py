"""The chat's tools (chat-director D003). Each reads only chat_api views, inside the director's
tenant transaction, so RLS decides what it can see; each applies the glossary's definitions in
its own SQL and returns one fixed kind of block.

A tool returns two things: the result for the model, and the blocks the director sees directly
(built from the database, never from the model's text: the model does not retype numbers).
"""

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from tools import (
    competency_risk,
    levels_summary,
    promotion,
    school,
    student_history,
    students_with_c,
)
from tools.base import Tool, ToolOutcome

__all__ = ["TOOLS", "TOOL_STATUS", "ToolOutcome", "run_tool"]

REGISTRY: dict[str, Tool] = {
    t.name: t
    for t in (
        school.TOOL,
        levels_summary.TOOL,
        students_with_c.TOOL,
        competency_risk.TOOL,
        promotion.TOOL,
        student_history.TOOL,
    )
}

TOOLS: list[dict[str, Any]] = [t.spec() for t in REGISTRY.values()]
TOOL_STATUS: dict[str, str] = {name: t.status for name, t in REGISTRY.items()}


async def run_tool(name: str, tool_input: Any, conn: AsyncConnection[DictRow]) -> ToolOutcome:
    tool = REGISTRY.get(name)
    if tool is None:
        return ToolOutcome(result={"error": f"unknown tool {name!r}"}, is_error=True)
    try:
        args = tool.check(tool_input)
    except ValueError as exc:
        return ToolOutcome(result={"error": str(exc)}, is_error=True)
    return await tool.run(conn, args)
