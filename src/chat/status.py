"""The status of a question in chat.question_bank, decided by the code from what the graph did
which tools ran and how they ended, never the model's prose.

- fuera_de_alcance: the out-of-scope tool ran.
- necesita_tool: sin_herramienta ran; tool_name is the missing topic (the backlog of tools).
- respondida: the answer ended normally and is backed by data. Either the last data tool of this
  answer ended clean (earlier calls of the same answer may have asked for options or found no
  data, as long as the model went on to a call that answered), or no tool ran because the thread
  already holds a clean data result: a follow-up or a synthesis of what is already there.
- parcial: everything else (the last data call answered with options, no data or an error; the
  answer was cut; or nothing in the thread backs it), so it is reviewed.
"""

from collections.abc import Iterable
from typing import Any

from chat.tools import DATA_TOOLS
from chat.tools.scope import NO_TOOL_TOOL, OUT_OF_SCOPE_TOOL

RESPONDIDA = "respondida"
NECESITA_TOOL = "necesita_tool"
PARCIAL = "parcial"
FUERA_DE_ALCANCE = "fuera_de_alcance"


def answered_with_data(call: dict[str, Any]) -> bool:
    """A data tool's call that ran and gave data: no error, no options to choose, no 'no data'."""
    if call.get("name") not in DATA_TOOLS or call.get("is_error"):
        return False
    result = call.get("result")
    return not (
        isinstance(result, dict) and ("sin_datos" in result or "necesita_aclaracion" in result)
    )


def _stopped_short(call: dict[str, Any]) -> bool:
    """True when the call failed or asked the director to clarify."""
    if call.get("is_error"):
        return True
    result = call.get("result")
    return isinstance(result, dict) and "necesita_aclaracion" in result


def question_status(
    tool_calls: list[dict[str, Any]],
    *,
    failed: bool,
    earlier: Iterable[dict[str, Any]] = (),
) -> tuple[str, str | None]:
    """(status, tool_name) for one answered question. tool_calls are the graph's reports for this
    answer (name, input, result, is_error); earlier, the reports of the thread's previous
    answers. failed is true when the answer ended in an error, a cut or the limit of model calls.
    tool_name is the first data tool of the answer (None for a follow-up answered from the
    thread)."""
    names = [call["name"] for call in tool_calls]
    if OUT_OF_SCOPE_TOOL.name in names:
        return FUERA_DE_ALCANCE, None
    for call in tool_calls:
        if call["name"] == NO_TOOL_TOOL.name:
            tema = str((call.get("input") or {}).get("tema") or "").strip()
            return NECESITA_TOOL, tema or None
    data = [call for call in tool_calls if call["name"] in DATA_TOOLS]
    if not data:
        backed = any(answered_with_data(call) for call in earlier)
        return (RESPONDIDA if backed and not failed else PARCIAL), None
    first = data[0]["name"]
    if failed or _stopped_short(data[-1]) or not any(answered_with_data(c) for c in data):
        return PARCIAL, first
    return RESPONDIDA, first
