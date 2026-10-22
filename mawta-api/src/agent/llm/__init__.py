"""How Mawta's agents call a language model.

One narrow operation: a single request that must answer by filling one JSON schema, so every
agent gets structured output it can validate before anything reaches the database. Agents depend
on the Model protocol; the Anthropic implementation is in anthropic.py and a scripted fake for
tests in fake.py.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


class PermanentError(Exception):
    """A failure that retrying will not fix: no API key, a request the provider rejects (4xx other
    than rate limits), or an answer that does not fill the schema. Anything else (rate limits,
    overload, 5xx, network, timeouts) is transient and worth retrying."""


@dataclass(frozen=True)
class Block:
    """One part of the system instructions. `cache` marks a stable block (instructions,
    curriculum) the provider may cache across calls."""

    text: str
    cache: bool = False


@dataclass(frozen=True)
class Tool:
    """The only way the model may answer: its input schema is the structured answer."""

    name: str
    description: str
    properties: dict[str, Any]
    required: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Request:
    system: list[Block]
    prompt: str
    tool: Tool
    max_tokens: int


@dataclass
class Usage:
    """What one call consumed, as the provider reports it."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class Response:
    """The structured answer the model produced (already decoded JSON)."""

    input: Any = None
    usage: Usage = field(default_factory=Usage)
    message_id: str = ""
    stop_reason: str = ""


class LLMError(Exception):
    """A failed call. `response` may still carry the usage of a call that was billed (an answer
    that did not fill the schema), so callers record it either way."""

    permanent: bool
    response: Response

    def __init__(self, message: str, *, permanent: bool, response: Response | None = None) -> None:
        super().__init__(message)
        self.permanent = permanent
        self.response = response or Response()


class Model(Protocol):
    name: str

    async def generate(self, req: Request) -> Response: ...


@dataclass(frozen=True)
class Prices:
    """A model's prices in US dollars per million tokens. They come from configuration: the
    server does not guess them, and with none a generation records its tokens and a zero,
    unknown cost."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    cache_read_per_mtok: float = 0.0
    cache_write_per_mtok: float = 0.0

    def known(self) -> bool:
        return self.input_per_mtok > 0 or self.output_per_mtok > 0

    def cost(self, u: Usage) -> float:
        m = 1_000_000.0
        return (
            u.input_tokens * self.input_per_mtok / m
            + u.output_tokens * self.output_per_mtok / m
            + u.cache_read_tokens * self.cache_read_per_mtok / m
            + u.cache_write_tokens * self.cache_write_per_mtok / m
        )
