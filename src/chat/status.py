"""The status of a question in chat.question_bank, decided by the code from what the graph did
(decision D017): which tools ran and how they ended, never the model's prose."""

from typing import Any

from chat.tools import DATA_TOOLS
from chat.tools.scope import NO_TOOL_TOOL, OUT_OF_SCOPE_TOOL

RESPONDIDA = "respondida"
NECESITA_TOOL = "necesita_tool"
PARCIAL = "parcial"
FUERA_DE_ALCANCE = "fuera_de_alcance"


def question_status(tool_calls: list[dict[str, Any]], *, failed: bool) -> tuple[str, str | None]:
    """(status, tool_name) for one answered question. tool_calls are the graph's reports: name,
    input, result, is_error. failed is true when the answer ended in an error, a cut or the limit
    of model calls."""
    names = [call["name"] for call in tool_calls]
    if OUT_OF_SCOPE_TOOL.name in names:
        return FUERA_DE_ALCANCE, None
    for call in tool_calls:
        if call["name"] == NO_TOOL_TOOL.name:
            tema = str((call.get("input") or {}).get("tema") or "").strip()
            return NECESITA_TOOL, tema or None
    data = [call for call in tool_calls if call["name"] in DATA_TOOLS]
    if not data:
        return PARCIAL, None  # answered without data: nothing backs it, so it is reviewed
    first = data[0]["name"]
    for call in data:
        result = call.get("result")
        if call.get("is_error") or (
            isinstance(result, dict) and ("sin_datos" in result or "necesita_aclaracion" in result)
        ):
            return PARCIAL, first
    return (PARCIAL if failed else RESPONDIDA), first
