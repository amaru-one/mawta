"""Traces (D006): nothing leaves without LANGFUSE_*; with Langfuse configured, one trace per
question carries the system prompt, the tools with input and output, the answer, latency and
tokens. Langfuse is exercised against an in-memory OpenTelemetry exporter: no network."""

import json
from collections.abc import Iterator
from contextlib import AsyncExitStack
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent.llm.providers import Endpoints, client_for, parse
from chat.service import ChatService
from chat.tracing import LangfuseTracer, NoTracer, traced_openai_client
from tests.chat.conftest import ANA, FakeLLM, Session, text_turn, tool_turn
from tests.chat.test_ask import ask
from tests.conftest import Databases, make_settings

ENDPOINTS = Endpoints(
    local_url="http://127.0.0.1:9/v1",
    local_api_key="",
    openrouter_url="https://openrouter.ai/api/v1",
    openrouter_api_key="",
)


def test_without_the_variables_nothing_is_configured(databases: Databases, tmp_path: Any):
    settings = make_settings(databases, tmp_path)
    assert not settings.langfuse_ready()
    settings = make_settings(databases, tmp_path, langfuse_host="https://cloud.langfuse.com")
    assert not settings.langfuse_ready(), "the host alone is not enough"


async def test_without_the_variables_the_chat_uses_the_plain_client_and_no_tracer(
    databases: Databases, tmp_path: Any
):
    service = ChatService(make_settings(databases, tmp_path), llm=FakeLLM())
    async with AsyncExitStack() as stack:
        await service.start(stack)
        assert isinstance(service.tracer, NoTracer)
    client = client_for(parse("local:x"), ENDPOINTS, timeout=1.0)
    assert type(client) is AsyncOpenAI


def test_with_langfuse_the_model_client_is_the_traced_one():
    traced = traced_openai_client()
    client = client_for(parse("local:x"), ENDPOINTS, timeout=1.0, client_cls=traced)
    assert isinstance(client, AsyncOpenAI) and type(client) is traced


@pytest.fixture(scope="module")
def langfuse() -> Iterator[tuple[LangfuseTracer, InMemorySpanExporter]]:
    from langfuse import Langfuse

    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:9",
        span_exporter=exporter,
    )
    yield LangfuseTracer(client), exporter
    client.shutdown()


def _text(span: Any) -> str:
    """Every attribute of the span as readable text: Langfuse stores input, output and metadata as
    JSON strings with non-ASCII escaped, so each one is decoded before the whole is dumped."""
    decoded: dict[str, Any] = {}
    for key, value in dict(span.attributes or {}).items():
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        decoded[key] = value
    return json.dumps(decoded, default=str, ensure_ascii=False)


async def test_a_question_becomes_one_trace_with_its_tools_and_answer(
    chat_client_for: Any,
    session: Session,
    fake_llm: FakeLLM,
    langfuse: tuple[LangfuseTracer, InMemorySpanExporter],
):
    tracer, exporter = langfuse
    exporter.clear()
    client: httpx.AsyncClient = await chat_client_for(fake_llm, chat_tracer=tracer)
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(), text_turn("Tres secciones: 2do A, 3ro A y 5to B."))

    await ask(client, me, thread["id"], "¿Qué secciones tiene mi colegio?")
    tracer.flush()

    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"chat.question", "datos_del_colegio"}
    question, tool = spans["chat.question"], spans["datos_del_colegio"]
    assert tool.parent is not None and question.context is not None
    assert tool.parent.span_id == question.context.span_id

    q = _text(question)
    assert "¿Qué secciones tiene mi colegio?" in q
    assert "You are Mawta's data assistant" in q, "the system prompt"
    assert "Tres secciones: 2do A, 3ro A y 5to B." in q, "the final answer"
    assert 'model_calls": 2' in q and 'input_tokens": 250' in q and 'output_tokens": 30' in q
    assert 'latency_ms"' in q and f"{ANA}:{thread['id']}" in q, "the thread tags the trace"

    t = _text(tool)
    assert "2do A" in t and "5to B" in t, "the tool's output"


async def test_a_failing_tool_marks_its_span_as_an_error(
    chat_client_for: Any,
    session: Session,
    fake_llm: FakeLLM,
    langfuse: tuple[LangfuseTracer, InMemorySpanExporter],
):
    tracer, exporter = langfuse
    exporter.clear()
    client: httpx.AsyncClient = await chat_client_for(fake_llm, chat_tracer=tracer)
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(arguments="{no es json"), text_turn("No pude consultarlo."))

    await ask(client, me, thread["id"], "¿Qué secciones hay?")
    tracer.flush()

    tool = next(s for s in exporter.get_finished_spans() if s.name == "datos_del_colegio")
    assert "ERROR" in _text(tool) and "not valid JSON" in _text(tool)
