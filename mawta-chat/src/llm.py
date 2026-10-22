"""The model behind the chat, behind a small interface so tests can swap it."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from anthropic import AsyncAnthropic
from anthropic.lib.tools import BetaToolLike
from anthropic.types.beta import BetaMessageParam

# Server-side refusal fallback (Claude API): if the model declines on a safety
# classifier, the API re-runs the request on a fallback model it chooses.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

Effort = Literal["low", "medium", "high", "xhigh", "max"]


@dataclass
class ModelTurn:
    # The assistant content exactly as returned (dicts), replayed unchanged in
    # later requests: the history is append-only.
    content: list[dict[str, Any]]
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
    ) -> ModelTurn: ...


class AnthropicLLM:
    def __init__(self, api_key: str, model: str, effort: Effort, max_tokens: int) -> None:
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.effort: Effort = effort
        self.max_tokens = max_tokens

    async def respond(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_text: Callable[[str], None],
    ) -> ModelTurn:
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            # The history and tools are kept as the API's own JSON shapes, so
            # they are only relabelled here, not converted.
            messages=cast(list[BetaMessageParam], messages),
            tools=cast(list[BetaToolLike], tools),
            output_config={"effort": self.effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            async for evt in stream:
                if evt.type == "text":
                    on_text(evt.text)
            final = await stream.get_final_message()
        return ModelTurn(
            content=[block.model_dump(mode="json", exclude_none=True) for block in final.content],
            stop_reason=final.stop_reason,
            model=final.model,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        )
