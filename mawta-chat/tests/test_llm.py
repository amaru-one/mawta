"""The OpenAI-compatible client and the model settings, without a database."""

from collections.abc import AsyncIterator
from typing import Any, cast, final

import pytest
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk
from pydantic import SecretStr, ValidationError

from llm import OpenAICompatLLM
from providers import parse
from settings import Settings

BASE: dict[str, Any] = {
    "_env_file": None,
    "chat_database_url": "postgres://x",
    "langgraph_database_url": "postgres://y",
    "chat_token_public_keys": {"k": "v"},
}


def chunk(
    delta: dict[str, Any], finish: str | None = None, usage: Any = None
) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            "usage": usage,
        }
    )


def usage_chunk() -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "m",
            "choices": [],
            "usage": {"prompt_tokens": 50, "completion_tokens": 7, "total_tokens": 57},
        }
    )


@final
class FakeCompletions:
    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self.chunks = chunks
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> AsyncIterator[ChatCompletionChunk]:
        self.kwargs = kwargs

        async def stream() -> AsyncIterator[ChatCompletionChunk]:
            for c in self.chunks:
                yield c

        return stream()


@final
class FakeClient:
    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self.completions = FakeCompletions(chunks)
        self.chat = self


async def test_stream_assembles_text_and_tool_calls():
    chunks = [
        chunk({"role": "assistant", "content": "Un "}),
        chunk({"content": "momento."}),
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_9",
                        "type": "function",
                        "function": {"name": "secciones_", "arguments": '{"a"'},
                    }
                ]
            }
        ),
        chunk(
            {"tool_calls": [{"index": 0, "function": {"name": "del_colegio", "arguments": ": 1}"}}]}
        ),
        chunk({}, finish="tool_calls"),
        usage_chunk(),
    ]
    fake = FakeClient(chunks)
    llm = OpenAICompatLLM(
        cast(AsyncOpenAI, cast(object, fake)), parse("openrouter:qwen/qwen3"), max_tokens=100
    )
    seen: list[str] = []

    turn = await llm.respond("sys", [{"role": "user", "content": "hola"}], [], seen.append)

    assert seen == ["Un ", "momento."]
    assert turn.message["content"] == "Un momento."
    assert turn.message["tool_calls"] == [
        {
            "id": "call_9",
            "type": "function",
            "function": {"name": "secciones_del_colegio", "arguments": '{"a": 1}'},
        }
    ]
    assert turn.stop_reason == "tool_calls"
    assert (turn.model, turn.input_tokens, turn.output_tokens) == ("openrouter:qwen/qwen3", 50, 7)
    sent = fake.completions.kwargs
    assert sent["model"] == "qwen/qwen3"
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert sent["extra_body"] == {"provider": {"require_parameters": True}}


async def test_a_plain_answer_has_no_tool_calls():
    fake = FakeClient([chunk({"content": "Hola"}, finish="stop")])
    llm = OpenAICompatLLM(
        cast(AsyncOpenAI, cast(object, fake)), parse("local:gemma4:12b-it-qat"), 10
    )

    turn = await llm.respond("s", [], [], lambda _: None)

    assert turn.message == {"role": "assistant", "content": "Hola"}
    assert fake.completions.kwargs["model"] == "gemma4:12b-it-qat"
    assert fake.completions.kwargs["extra_body"] is None


async def test_reasoning_effort_is_sent_only_when_set():
    fake = FakeClient([chunk({"content": "Hola"}, finish="stop")])
    llm = OpenAICompatLLM(cast(AsyncOpenAI, cast(object, fake)), parse("local:m"), 10, "none")

    await llm.respond("s", [], [], lambda _: None)

    assert fake.completions.kwargs["extra_body"] == {"reasoning_effort": "none"}


def test_chat_model_must_be_provider_model():
    cfg = Settings(**BASE, chat_model="local:gemma4:12b-it-qat")
    assert str(cfg.model_ref()) == "local:gemma4:12b-it-qat"
    for bad in ("gemma4", "anthropic:claude"):
        with pytest.raises(ValidationError):
            Settings(**BASE, chat_model=bad)


def test_openrouter_needs_its_key():
    with pytest.raises(ValidationError):
        Settings(**BASE, chat_model="openrouter:qwen/qwen3")
    cfg = Settings(**BASE, chat_model="openrouter:qwen/qwen3", openrouter_api_key=SecretStr("k"))
    assert cfg.model_ref().provider == "openrouter"
