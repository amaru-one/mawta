"""Traces of the director chat (decision D006): one trace per question, with the system prompt,
every model call, every tool with its input and output, the final answer, latency and tokens.

The chat talks to a small Tracer interface, so the rest of the code never imports Langfuse:
- NoTracer does nothing. It is what runs without LANGFUSE_* (nothing is sent anywhere).
- LangfuseTracer sends to Langfuse Cloud (or any instance LANGFUSE_HOST names). The model calls
  themselves are recorded by Langfuse's wrapper of the openai client (see service.py), nested
  under the question's span because that span is the current OpenTelemetry context while the
  graph runs.

Tests use a recording tracer of their own against this same interface.
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Any, Protocol

from chat.llm import ModelTurn


class QuestionTrace(Protocol):
    """One question being answered."""

    def tool(self, name: str, tool_input: Any) -> AbstractContextManager["ToolSpan"]: ...

    def model_turn(self, turn: ModelTurn) -> None: ...

    def finish(
        self, *, answer: str, blocks: list[dict[str, Any]], latency_ms: int, stop_reason: str
    ) -> None: ...


class ToolSpan(Protocol):
    def result(self, result: Any, is_error: bool) -> None: ...


class Tracer(Protocol):
    def question(
        self, *, thread_key: str, user_id: str, question: str, system: str
    ) -> AbstractContextManager[QuestionTrace]: ...


# --- nothing -------------------------------------------------------------------------------


class _NoToolSpan:
    def result(self, result: Any, is_error: bool) -> None:
        return None


class _NoQuestion:
    def tool(self, name: str, tool_input: Any) -> AbstractContextManager[ToolSpan]:
        return nullcontext(_NoToolSpan())

    def model_turn(self, turn: ModelTurn) -> None:
        return None

    def finish(
        self, *, answer: str, blocks: list[dict[str, Any]], latency_ms: int, stop_reason: str
    ) -> None:
        return None


class NoTracer:
    """Without LANGFUSE_*: the chat behaves exactly as before and sends nothing."""

    def question(
        self, *, thread_key: str, user_id: str, question: str, system: str
    ) -> AbstractContextManager[QuestionTrace]:
        return nullcontext(_NoQuestion())


# --- Langfuse ------------------------------------------------------------------------------


class _LangfuseToolSpan:
    def __init__(self, span: Any) -> None:
        self.span = span

    def result(self, result: Any, is_error: bool) -> None:
        self.span.update(output=result, level="ERROR" if is_error else None)


class _LangfuseQuestion:
    def __init__(self, client: Any, span: Any) -> None:
        self.client = client
        self.span = span
        self.model_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.model: str | None = None

    @contextmanager
    def tool(self, name: str, tool_input: Any) -> Iterator[ToolSpan]:
        with self.client.start_as_current_observation(
            as_type="tool", name=name, input=tool_input
        ) as span:
            yield _LangfuseToolSpan(span)

    def model_turn(self, turn: ModelTurn) -> None:
        # The call itself (prompt, completion, usage) is the generation Langfuse's openai
        # wrapper records; here only the totals of the question.
        self.model_calls += 1
        self.input_tokens += turn.input_tokens
        self.output_tokens += turn.output_tokens
        self.model = turn.model

    def finish(
        self, *, answer: str, blocks: list[dict[str, Any]], latency_ms: int, stop_reason: str
    ) -> None:
        self.span.update(
            output={"answer": answer, "blocks": [b["tipo"] for b in blocks]},
            metadata={
                "model": self.model,
                "model_calls": self.model_calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "latency_ms": latency_ms,
                "stop_reason": stop_reason,
            },
        )


class LangfuseTracer:
    """Sends each question to Langfuse as a trace tagged with its thread."""

    def __init__(self, client: Any) -> None:
        self.client = client

    @classmethod
    def connect(cls, *, host: str, public_key: str, secret_key: str) -> "LangfuseTracer":
        from langfuse import Langfuse

        return cls(Langfuse(public_key=public_key, secret_key=secret_key, base_url=host))

    @contextmanager
    def question(
        self, *, thread_key: str, user_id: str, question: str, system: str
    ) -> Iterator[QuestionTrace]:
        from langfuse import propagate_attributes

        with (
            propagate_attributes(session_id=thread_key, user_id=user_id, tags=["chat-director"]),
            self.client.start_as_current_observation(
                as_type="agent",
                name="chat.question",
                input={"question": question, "system": system},
                metadata={"thread": thread_key},
            ) as span,
        ):
            yield _LangfuseQuestion(self.client, span)

    def flush(self) -> None:
        self.client.flush()

    def shutdown(self) -> None:
        self.client.shutdown()


no_question: QuestionTrace = _NoQuestion()


def traced_openai_client() -> type[Any]:
    """Langfuse's drop-in subclass of openai.AsyncOpenAI: same API, every call recorded."""
    from langfuse.openai import (
        AsyncOpenAI as TracedAsyncOpenAI,  # pyright: ignore[reportPrivateImportUsage]
    )

    return TracedAsyncOpenAI
