"""Some models write a tool call as text instead of calling it: the demo's model answers an
out-of-scope question with the words «fuera_de_alcance», or «sin_herramienta {"tema": …}», and
the director would read them (official evaluation, 2026-11-16).

ScopeTextGuard sits between the model's text stream and the director. While the text could still
be one of the two scope tools' names it holds it back; as soon as it cannot, it lets everything
through. When the model's turn ends and the held text is exactly such a "call", the turn becomes
a real tool call, so the graph answers exactly as if the model had called the tool.
"""

import dataclasses
import json
import re
import uuid
from collections.abc import Callable
from typing import Any

from chat.llm import ModelTurn
from chat.tools.scope import NO_TOOL_TOOL, OUT_OF_SCOPE_TOOL

NAMES = (OUT_OF_SCOPE_TOOL.name, NO_TOOL_TOOL.name)
# Past this length a text is prose that happens to start with a tool's name: stop holding it.
MAX_HELD = 400
_CALL = re.compile(
    r"^[\s`]*(" + "|".join(NAMES) + r")\s*(\{.*\}|\(.*\))?[\s`]*$",
    re.DOTALL,
)


class ScopeTextGuard:
    def __init__(self, emit: Callable[[str], None]) -> None:
        self.emit = emit
        self.held = ""
        self.passing = False

    def feed(self, text: str) -> None:
        """The model's text as it streams."""
        if self.passing:
            self.emit(text)
            return
        self.held += text
        if not self._could_be_a_call(self.held):
            self.passing = True
            held, self.held = self.held, ""
            self.emit(held)

    def finish(self, turn: ModelTurn) -> ModelTurn:
        """The turn as the graph should see it: a written scope call becomes a real one."""
        held, self.held = self.held, ""
        if self.passing or not held.strip():
            return turn
        match = _CALL.match(held)
        if match is None:
            self.emit(held)
            return turn
        if turn.message.get("tool_calls"):
            # It called a tool as well: keep the real call, drop the written one.
            return dataclasses.replace(turn, message={**turn.message, "content": None})
        call = {
            "id": f"call_text_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {
                "name": match.group(1),
                "arguments": json.dumps(_arguments(match.group(2)), ensure_ascii=False),
            },
        }
        message: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": [call]}
        return dataclasses.replace(turn, message=message, stop_reason="tool_calls")

    @staticmethod
    def _could_be_a_call(text: str) -> bool:
        s = text.lstrip(" \t\n`")
        if not s:
            return True
        if len(s) > MAX_HELD:
            return False
        return any(name.startswith(s) or s.startswith(name) for name in NAMES)


def _arguments(raw: str | None) -> dict[str, Any]:
    """{"tema": "x"} or (tema="x") as written; anything else is no arguments."""
    if not raw:
        return {}
    text = raw.strip()
    if text.startswith("{"):
        try:
            value = json.loads(text)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    found = re.search(r"tema\s*[=:]\s*[\"']([^\"']*)[\"']", text)
    return {"tema": found.group(1)} if found else {}
