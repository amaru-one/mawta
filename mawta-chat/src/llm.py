"""The model behind the chat, behind a small interface so tests can swap it.

It speaks the OpenAI-compatible chat completions API, so the same code runs on the school's own
model server (Ollama, vLLM: "local") or on OpenRouter: CHAT_MODEL says which
("local:gemma4:12b-it-qat", "openrouter:qwen/qwen3-30b-a3b").
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

from providers import ModelRef, extra_body


@dataclass
class ModelTurn:
    # The assistant message exactly as it goes back into later requests, in the
    # API's own shape: {"role": "assistant", "content": ..., "tool_calls": [...]}.
    # The history is append-only.
    message: dict[str, Any]
    # The completion's finish_reason: "stop", "tool_calls", "length" or
    # "content_filter".
    stop_reason: str | None
    model: str
    input_tokens: int
    output_tokens: int


class LLM(Protocol):
    model: str

    async def respond(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_text: Callable[[str], None],
        /,
    ) -> ModelTurn: ...


class OpenAICompatLLM:
    client: AsyncOpenAI
    ref: ModelRef
    model: str
    max_tokens: int
    reasoning_effort: str

    def __init__(
        self, client: AsyncOpenAI, ref: ModelRef, max_tokens: int, reasoning_effort: str = ""
    ) -> None:
        self.client = client
        self.ref = ref
        self.reasoning_effort = reasoning_effort
        # The whole "provider:model", which is what chat.messages records.
        self.model = str(ref)
        self.max_tokens = max_tokens

    async def respond(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_text: Callable[[str], None],
    ) -> ModelTurn:
        stream = await self.client.chat.completions.create(
            model=self.ref.model,
            max_tokens=self.max_tokens,
            # The history and tools are kept in the API's own JSON shapes, so
            # they are only relabelled here, not converted.
            messages=[
                {"role": "system", "content": system},
                *cast(list[ChatCompletionMessageParam], messages),
            ],
            tools=cast(list[ChatCompletionToolParam], tools),
            stream=True,
            stream_options={"include_usage": True},
            extra_body=extra_body(self.ref, self.reasoning_effort),
        )
        text: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        finish: str | None = None
        input_tokens = output_tokens = 0
        async for chunk in stream:
            if chunk.usage is not None:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta.content:
                text.append(delta.content)
                on_text(delta.content)
            # A tool call arrives in pieces keyed by its index: the id and name
            # first, then the arguments a few characters at a time.
            for piece in delta.tool_calls or []:
                call = calls.setdefault(
                    piece.index,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if piece.id:
                    call["id"] = piece.id
                if piece.function is not None:
                    if piece.function.name:
                        call["function"]["name"] += piece.function.name
                    if piece.function.arguments:
                        call["function"]["arguments"] += piece.function.arguments
            if choice.finish_reason is not None:
                finish = choice.finish_reason
        message: dict[str, Any] = {"role": "assistant", "content": "".join(text) or None}
        if calls:
            message["tool_calls"] = [calls[i] for i in sorted(calls)]
        return ModelTurn(
            message=message,
            stop_reason=finish,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
