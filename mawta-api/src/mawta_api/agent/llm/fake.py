"""A scripted Model for tests."""

from dataclasses import dataclass, field
from typing import Any

from mawta_api.agent.llm import LLMError, Request, Response, Usage


@dataclass
class FakeReply:
    """One scripted answer of a Fake: a tool input (a JSON string or an already-decoded value),
    or an error."""

    input: Any = None
    error: LLMError | None = None
    usage: Usage = field(default_factory=Usage)


@dataclass
class Fake:
    """Answers each call with the next reply and records every request, so a test can assert what
    the agent sent (and that it sent nothing when there was nothing to generate)."""

    replies: list[FakeReply] = field(default_factory=list)
    calls: list[Request] = field(default_factory=list)
    name: str = "fake-model"

    async def generate(self, req: Request) -> Response:
        import json

        self.calls.append(req)
        if not self.replies:
            raise LLMError("llm: fake has no more replies", permanent=True)
        reply = self.replies.pop(0)
        value = json.loads(reply.input) if isinstance(reply.input, str) else reply.input
        resp = Response(input=value, usage=reply.usage, message_id="fake", stop_reason="tool_use")
        if reply.error is not None:
            reply.error.response = resp
            raise reply.error
        return resp

    def call_count(self) -> int:
        return len(self.calls)
