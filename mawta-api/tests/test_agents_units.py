"""Unit tests of the pieces around the agents: the conclusion guard, the OpenAI-compatible
client (providers, schema, answers, errors), the STT client and the transcribe handler."""

import base64
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from openai.types.chat import ChatCompletion
from psycopg import AsyncConnection
from psycopg.rows import DictRow

import applog
from agent.conclusions import Material
from agent.conclusions.guard import guard, name_words
from agent.llm import LLMError
from agent.llm.openai_compat import OpenAICompat, classify, read_completion, strict_schema
from agent.llm.providers import Endpoints, configured, extra_body, parse
from db import returned
from stt import Client, SttError, SttPermanentError
from tests.conftest import Admin
from tests.conftest import Client as AppClient
from worker.handlers.transcribe import voice_note_transcribe

# ------------------------------------------------------------- conclusion material --


def _material(standard: dict[str, Any] | None) -> Material:
    from agent.conclusions import Scope

    ids = [uuid.uuid4() for _ in range(4)]
    m = Material(scope=Scope(*ids), level="B", requirement="level_b", standard=standard)
    m.competency = {
        "code": "COM-C1",
        "name": "Se comunica oralmente",
        "description": None,
        "capabilities": [{"id": uuid.uuid4(), "name": "Obtiene información"}],
    }
    return m


def test_render_puts_the_expected_standard_before_the_level():
    from agent.conclusions import render

    text, _ = render(
        _material({"level": 5, "cycle": "ciclo_v", "text": "Se comunica oralmente mediante…"})
    )
    assert "Expected standard (CNEB level 5, the level expected at the end of cycle V):" in text
    assert "Se comunica oralmente mediante…" in text
    assert text.index("Expected standard") < text.index("Achievement level asserted")


def test_render_says_when_there_is_no_standard():
    from agent.conclusions import render

    text, _ = render(_material(None))
    assert "Expected standard: not available for this competency." in text


# ----------------------------------------------------------------- guard --


def test_guard_rejects_tokens_and_capitalised_names_only():
    names = name_words(
        [
            {
                "given_name": "Rosa María",
                "paternal_surname": "Quispe",
                "preferred_name": None,
                "maternal_surname": "Gil",
            }
        ]  # fmt: skip
    )
    assert "Gil" in names and "Quispe" in names
    assert guard("Avanza en [ESTUDIANTE] bien", names)
    assert guard("Rosa avanza mucho", names)
    assert guard("Maria avanza mucho", names)  # accents folded
    assert guard("Cultivó una rosa en clase", names) == ""  # common word, not capitalised
    assert guard("Resuelve problemas de cantidad", names) == ""


# ------------------------------------------------------------------- llm --


def test_strict_schema_closes_every_object_without_mutating_input():
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {}}}},
    }
    before = json.dumps(schema)
    out = strict_schema(schema)
    assert out["additionalProperties"] is False
    assert out["properties"]["items"]["items"]["additionalProperties"] is False
    assert json.dumps(schema) == before


def test_classify_provider_errors():
    import httpx2  # the HTTP client the openai SDK is typed against
    import openai

    def status(code: int) -> openai.APIStatusError:
        resp = httpx2.Response(code, request=httpx2.Request("POST", "https://x"))
        return openai.APIStatusError("boom", response=resp, body=None)

    assert classify(status(429)).permanent is False
    assert classify(status(503)).permanent is False
    assert classify(status(408)).permanent is False
    assert classify(status(400)).permanent is True
    assert classify(status(404)).permanent is True
    assert classify(RuntimeError("net")).permanent is False
    assert isinstance(classify(status(400)), LLMError)


def test_parse_provider_model():
    ref = parse("ollama:gemma4:12b-it-qat")
    assert (ref.provider, ref.model) == ("ollama", "gemma4:12b-it-qat")
    assert str(ref) == "ollama:gemma4:12b-it-qat"
    ref = parse(" openrouter:qwen/qwen3-30b-a3b ")
    assert (ref.provider, ref.model) == ("openrouter", "qwen/qwen3-30b-a3b")
    for bad in ("gemma4", "ollma:gemma4", "ollama:", ":gemma4"):
        with pytest.raises(ValueError):
            parse(bad)


def test_provider_configured_and_extra_body():
    ep = Endpoints(
        ollama_url="http://127.0.0.1:11434/v1",
        ollama_api_key="",
        openrouter_url="https://openrouter.ai/api/v1",
        openrouter_api_key="",
    )
    assert configured(parse("ollama:x"), ep)
    assert not configured(parse("openrouter:x"), ep)  # no key
    keyed = Endpoints(ep.ollama_url, "", ep.openrouter_url, "k")
    assert configured(parse("openrouter:x"), keyed)
    assert extra_body(parse("openrouter:x")) == {"provider": {"require_parameters": True}}
    assert extra_body(parse("ollama:x")) is None


def _completion(
    content: str | None,
    finish: str = "stop",
    refusal: str | None = None,
    cached: int | None = None,
) -> ChatCompletion:
    usage: dict[str, Any] = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return ChatCompletion.model_validate(
        {
            "id": "cmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish,
                    "message": {"role": "assistant", "content": content, "refusal": refusal},
                }
            ],
            "usage": usage,
        }
    )


def test_read_completion_answers_and_usage():
    resp = read_completion(_completion('{"a": 1}', cached=100))
    assert resp.input == {"a": 1}
    assert (resp.usage.input_tokens, resp.usage.output_tokens) == (120, 30)
    assert resp.usage.cache_read_tokens == 100
    assert read_completion(_completion('```json\n{"a": 2}\n```')).input == {"a": 2}
    assert read_completion(_completion('{"a": 3}')).usage.cache_read_tokens == 0


def test_read_completion_unusable_answers_are_permanent_and_keep_usage():
    cases = [
        _completion("not json"),
        _completion('{"a": 1', finish="length"),
        _completion(None, finish="content_filter"),
        _completion(None, refusal="no"),
    ]
    for completion in cases:
        with pytest.raises(LLMError) as err:
            read_completion(completion)
        assert err.value.permanent is True
        assert err.value.response.usage.input_tokens == 120


def test_settings_validate_agent_models():
    from pydantic import ValidationError

    from settings import Settings

    cfg = Settings(database_url="postgres://x", planning_agent_model="ollama:gemma4:12b-it-qat")
    ref = cfg.agent_model("planning")
    assert ref is not None and str(ref) == "ollama:gemma4:12b-it-qat"
    assert cfg.agent_model("conclusions") is None  # empty: that agent is unavailable
    with pytest.raises(ValidationError):
        Settings(database_url="postgres://x", conclusions_agent_model="gemma4")


async def test_unconfigured_model_fails_permanently():
    from agent.llm import Request, Tool

    req = Request(system=[], prompt="x", tool=Tool("t", "d", {}), max_tokens=10)
    with pytest.raises(LLMError) as err:
        await OpenAICompat(None, None).generate(req)
    assert err.value.permanent is True


# ------------------------------------------------------------------- stt --


def make_stt(handler: Callable[[httpx.Request], httpx.Response], key: str = "k") -> Client:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Client(key, "m", endpoint="https://stt.test/x", http=http)


async def test_stt_success_reports_provider_usage_and_never_the_audio():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200, json={"text": "hola", "id": "gen-1", "usage": {"cost": 0, "audio_seconds": 3.5}}
        )

    text, usage = await make_stt(handler).transcribe_with_usage(b"audio")
    assert text == "hola" and usage.cost_usd == 0 and usage.audio_seconds == 3.5
    assert usage.generation_id == "gen-1"
    assert seen["auth"] == "Bearer k" and seen["body"]["language"] == "es"
    assert base64.b64decode(seen["body"]["input_audio"]["data"]) == b"audio"


async def test_stt_error_classes():
    with pytest.raises(SttPermanentError):
        await make_stt(lambda r: httpx.Response(200), key="").transcribe(b"x")
    with pytest.raises(SttPermanentError):
        await make_stt(lambda r: httpx.Response(400)).transcribe(b"x")
    for code in (429, 500):
        with pytest.raises(SttError) as err:
            await make_stt(lambda r, c=code: httpx.Response(c)).transcribe(b"x")
        assert not isinstance(err.value, SttPermanentError)


# -------------------------------------------------------------- transcribe --


class FakeTranscriber:
    text: str
    error: Exception | None

    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text, self.error = text, error

    async def transcribe(self, _audio_mp3: bytes) -> str:
        if self.error:
            raise self.error
        return self.text


async def insert_note(admin: Admin, audio: bytes = b"fake") -> uuid.UUID:
    from tests.conftest import FX

    note = uuid.uuid4()
    await admin.execute(
        "insert into voice_notes (id, tenant_id, session_id, student_id, class_id, teacher_id,"
        " duration_ms, audio, mime_type, byte_size) values (%s,%s,%s,%s,%s,%s,5000,%s,'audio/mpeg',4)",
        (
            note,
            FX.tenant_a,
            FX.session_one,
            FX.students[0],
            FX.class_mat_5b,
            FX.teacher_quispe,
            audio,
        ),
    )
    return note


async def run_handler(
    client: AppClient,
    handler: Callable[[AsyncConnection[DictRow], int, dict[str, Any]], Awaitable[None]],
    note: uuid.UUID,
) -> applog.OutcomeReport:
    from db import TenantCtx
    from tests.conftest import FX

    db = client.app.state.api.db
    report, token = applog.begin_outcome_report()
    try:
        async with db.tenant_tx(TenantCtx(tenant_id=FX.tenant_a, request_id="job:test")) as conn:
            await handler(conn, 1, {"voice_note_id": str(note)})
    finally:
        applog.end_outcome_report(token)
    return report


async def note_state(admin: Admin, note: uuid.UUID) -> DictRow:
    cur = await admin.execute(
        "select transcription_status, transcript from voice_notes where id = %s", (note,)
    )
    return returned(await cur.fetchone())


async def test_transcribe_success_saves_the_transcript(client: AppClient, admin: Admin):
    note = await insert_note(admin)
    try:
        await run_handler(client, voice_note_transcribe(FakeTranscriber("prueba")), note)
        row = await note_state(admin, note)
        assert (row["transcription_status"], row["transcript"]) == ("completed", "prueba")
    finally:
        await admin.execute("delete from voice_notes where id = %s", (note,))


async def test_transcribe_permanent_failure_is_recorded_not_retried(
    client: AppClient, admin: Admin
):
    note = await insert_note(admin)
    try:
        handler = voice_note_transcribe(FakeTranscriber(error=SttPermanentError("no key")))
        report = await run_handler(client, handler, note)
        assert report.outcome == applog.OUTCOME_PERMANENT_FAILURE
        row = await note_state(admin, note)
        assert row["transcription_status"] == "failed" and row["transcript"] is None
    finally:
        await admin.execute("delete from voice_notes where id = %s", (note,))


async def test_transcribe_transient_error_propagates_and_discarded_note_is_skipped(
    client: AppClient, admin: Admin
):
    note = await insert_note(admin)
    try:
        with pytest.raises(SttError):
            await run_handler(
                client, voice_note_transcribe(FakeTranscriber(error=SttError("x"))), note
            )
        assert (await note_state(admin, note))["transcription_status"] != "failed"
    finally:
        await admin.execute("delete from voice_notes where id = %s", (note,))
    report = await run_handler(client, voice_note_transcribe(FakeTranscriber("x")), uuid.uuid4())
    assert report.outcome == applog.OUTCOME_SKIPPED
