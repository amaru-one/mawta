"""Unit tests of the pieces around the agents: redaction replace, the conclusion guard, the
OpenAI-compatible client (providers, schema, answers, errors), the STT client and the
transcribe handler."""

import base64
import datetime as dt
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from openai.types.chat import ChatCompletion
from psycopg.rows import DictRow
from sqlalchemy.ext.asyncio import AsyncConnection

import applog
from agent import InvalidAnswer
from agent.conclusions import NO_DIFFICULTIES_AD, Material, render, validate
from agent.conclusions.guard import guard, name_words
from agent.llm import LLMError
from agent.llm.openai_compat import OpenAICompat, classify, read_completion, strict_schema
from agent.llm.providers import Endpoints, configured, extra_body, parse
from agent.redaction.replace import Fragment, LocateError, attribution, locate, redact
from repo import redaction as rrepo
from stt import Client, SttError, SttPermanentError
from tests.conftest import Admin, returned
from tests.conftest import Client as AppClient
from worker.handlers.transcribe import voice_note_transcribe


def frag(text: str, refers_to: str = "other_person", key: str = "") -> Fragment:
    return Fragment(text, refers_to, key)


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
    text, _ = render(
        _material({"level": 5, "cycle": "ciclo_v", "text": "Se comunica oralmente mediante…"})
    )
    assert "Expected standard (CNEB level 5, the level expected at the end of cycle V):" in text
    assert "Se comunica oralmente mediante…" in text
    assert text.index("Expected standard") < text.index("Achievement level asserted")


def test_render_says_when_there_is_no_standard():
    text, _ = render(_material(None))
    assert "Expected standard: not available for this competency." in text


# ------------------------------------------------------------- conclusion answer --


def _graded_material(level: str = "B", requirement: str = "level_b") -> Material:
    """A material with two graded evidences (E1, E2) and one voice note (N1)."""
    m = _material(None)
    m.level, m.requirement = level, requirement
    capability = m.competency["capabilities"][0]["id"]
    m.evidences = [
        {
            "id": uuid.uuid4(),
            "title": title,
            "kind": kind,
            "description": None,
            "score_status": "graded",
            "scale_level": "B",
            "raw_value": None,
            "max_value": None,
            "feedback": None,
            "experience_id": uuid.uuid4(),
            "criteria": [{"description": "Explica sus ideas.", "capability_ids": [capability]}],
        }
        for title, kind in (("Relato oral", "actuacion"), ("Ficha de escucha", "produccion"))
    ]
    m.voice_notes = [
        {
            "id": uuid.uuid4(),
            "recorded_at": dt.datetime(2026, 5, 4, 9, 0),
            "session_topic": None,
            "transcript_redacted": "[ESTUDIANTE] ordenó bien su relato.",
        }
    ]
    m.graded = 2
    return m


def _point(text: str, evidences: list[str], notes: list[str] | None = None) -> dict[str, Any]:
    return {"texto": text, "evidencias": evidences, "notas": notes or []}


def _answer(**changes: Any) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "avances": [_point("Narra una experiencia con orden.", ["E1"], ["N1"])],
        "dificultades": [_point("Le cuesta hacer preguntas a quien expone.", ["E2"])],
        "recomendaciones": [_point("Se le recomienda anotar una pregunta al escuchar.", [])],
        "justificacion_sin_progreso": "",
        "apoyos_brindados": "",
        "notas_no_usadas": [],
    }
    return answer | changes


def _validate(m: Material, answer: Any, names: list[str] | None = None) -> dict[str, Any]:
    _, refs = render(m)
    return validate(m, refs, names or [], answer)


def test_validate_builds_the_proposal_from_a_grounded_answer():
    m = _graded_material()
    res = _validate(m, _answer())
    assert res["body"] == (
        "Narra una experiencia con orden. Le cuesta hacer preguntas a quien expone. "
        "Se le recomienda anotar una pregunta al escuchar."
    )
    assert res["level"] == "B"
    assert res["progress"][0]["evidence_ids"] == [m.evidences[0]["id"]]
    assert res["used_voice_note_ids"] == [m.voice_notes[0]["id"]]
    assert "no_progress_justification" not in res


def test_validate_rejects_an_answer_that_is_not_the_tool_object():
    with pytest.raises(InvalidAnswer, match="wrong type"):
        _validate(_graded_material(), ["avances"])


def test_validate_asks_every_progress_and_difficulty_for_a_citation():
    answer = _answer(avances=[_point("Narra una experiencia con orden.", [])])
    with pytest.raises(InvalidAnswer, match="no cita ninguna evidencia ni nota"):
        _validate(_graded_material(), answer)


def test_validate_rejects_a_reference_that_was_never_given():
    answer = _answer(dificultades=[_point("Le cuesta hacer preguntas.", ["E9"])])
    with pytest.raises(InvalidAnswer, match='cita la evidencia "E9"'):
        _validate(_graded_material(), answer)


def test_validate_rejects_a_name_of_the_roster_and_a_replacement_mark():
    named = _answer(avances=[_point("Lucía narra una experiencia con orden.", ["E1"])])
    with pytest.raises(InvalidAnswer, match="nombre de estudiante"):
        _validate(_graded_material(), named, names=["Lucía"])
    marked = _answer(avances=[_point("[ESTUDIANTE] narra con orden.", ["E1"])])
    with pytest.raises(InvalidAnswer, match="contiene la marca"):
        _validate(_graded_material(), marked)


def test_validate_keeps_the_no_difficulties_sentence_for_ad():
    answer = _answer(dificultades=[_point(NO_DIFFICULTIES_AD, ["E1"])])
    with pytest.raises(InvalidAnswer, match="solo vale en AD"):
        _validate(_graded_material(), answer)
    assert _validate(_graded_material("AD", "optional"), answer)["difficulties"]


def test_validate_holds_the_conclusion_to_the_siagie_length():
    long = "Explica con detalle " + "muy " * 80 + "claro."
    with pytest.raises(InvalidAnswer, match="SIAGIE acepta como máximo 350"):
        _validate(_graded_material(), _answer(avances=[_point(long, ["E1"])]))


def test_validate_requires_what_the_requirement_adds():
    with pytest.raises(InvalidAnswer, match="justificacion_sin_progreso es obligatoria"):
        _validate(_graded_material("C", "consecutive_c"), _answer())
    with pytest.raises(InvalidAnswer, match="apoyos_brindados es obligatorio"):
        _validate(_graded_material("B", "inclusion_support"), _answer())
    justified = _answer(justificacion_sin_progreso="Faltó a las sesiones de práctica.")
    res = _validate(_graded_material("C", "consecutive_c"), justified)
    assert res["no_progress_justification"] == "Faltó a las sesiones de práctica."


def test_validate_refuses_a_reference_written_inside_the_text():
    cited = _answer(avances=[_point("Narra una experiencia con orden (E1).", ["E1"])])
    with pytest.raises(InvalidAnswer, match=r"escribe la referencia \(E1\) dentro del texto"):
        _validate(_graded_material(), cited)
    grouped = _answer(dificultades=[_point("Le cuesta preguntar (E2 y N1).", ["E2"], ["N1"])])
    with pytest.raises(InvalidAnswer, match=r"\(E2 y N1\)"):
        _validate(_graded_material(), grouped)
    seen = _answer(dificultades=[_point("Le cuesta preguntar (ver N1).", ["E2"], ["N1"])])
    with pytest.raises(InvalidAnswer, match=r"\(ver N1\)"):
        _validate(_graded_material(), seen)
    justified = _answer(justificacion_sin_progreso="Faltó a las sesiones de práctica (N1).")
    with pytest.raises(InvalidAnswer, match="justificacion_sin_progreso escribe la referencia"):
        _validate(_graded_material("C", "consecutive_c"), justified)


def test_validate_keeps_parentheses_that_are_not_references():
    # N2 is not a reference of this material (it has N1 only): here it is nitrogen.
    plain = _answer(
        avances=[_point("Explica la presencia del nitrógeno (N2) en el aire.", ["E1"])],
        recomendaciones=[
            _point("Se le recomienda practicar con fracciones (medios y tercios).", [])
        ],
    )
    assert _validate(_graded_material(), plain)["body"].startswith("Explica la presencia")


def test_validate_lists_only_the_unused_notes_it_was_given():
    answer = _answer(
        avances=[_point("Narra una experiencia con orden.", ["E1"])],
        notas_no_usadas=[
            {"nota": "N1", "motivo": "Habla de conducta."},
            {"nota": "N7", "motivo": "No existe."},
        ],
    )
    m = _graded_material()
    res = _validate(m, answer)
    assert res["unused_voice_notes"] == [
        {"voice_note_id": m.voice_notes[0]["id"], "reason": "Habla de conducta."}
    ]


# ------------------------------------------------------------- redaction --


def test_locate_whole_words_longest_first_and_case_folded():
    transcript = "La mamá de Lucía vino. lucía habló con Juan."
    spans = locate(transcript, [frag("Lucía"), frag("la mamá de Lucía"), frag("Juan")])
    assert [transcript[s.start : s.end] for s in spans] == ["La mamá de Lucía", "lucía", "Juan"]


def test_locate_ignores_substrings_and_fails_on_missing_text():
    with pytest.raises(LocateError):
        locate("Anita vino", [frag("Ana")])
    with pytest.raises(LocateError):
        locate("hola", [frag("Pedro")])


def test_redact_numbers_classmates_by_first_appearance():
    transcript = "Luis y Marta ayudaron a Sofía; luego Luis se fue."
    frags = [
        frag("Sofía", "assigned_student"),
        frag("Luis", "classmate", "S1"),
        frag("Marta", "classmate", "S2"),
    ]
    spans = locate(transcript, frags)
    text, tokens = redact(transcript, spans)
    assert (
        text == "[COMPAÑERO_1] y [COMPAÑERO_2] ayudaron a [ESTUDIANTE]; luego [COMPAÑERO_1] se fue."
    )
    assert tokens == ["[COMPAÑERO_1]", "[COMPAÑERO_2]", "[ESTUDIANTE]", "[COMPAÑERO_1]"]


def test_attribution_rules():
    other = locate("Luis ayudó", [frag("Luis", "classmate", "S1")])
    assert attribution(other, False, False) == (
        rrepo.ATTRIBUTION_DISCARDED,
        rrepo.DISCARD_MENTIONS_OTHER_STUDENT,
    )
    assert attribution(other, False, True) == (rrepo.ATTRIBUTION_REASSIGNED, None)
    assert attribution([], True, True) == (rrepo.ATTRIBUTION_DISCARDED, rrepo.DISCARD_UNREADABLE)
    assert attribution([], False, False) == (rrepo.ATTRIBUTION_OK, None)


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
    ref = parse("local:gemma4:12b-it-qat")
    assert (ref.provider, ref.model) == ("local", "gemma4:12b-it-qat")
    assert str(ref) == "local:gemma4:12b-it-qat"
    ref = parse(" openrouter:qwen/qwen3-30b-a3b ")
    assert (ref.provider, ref.model) == ("openrouter", "qwen/qwen3-30b-a3b")
    for bad in ("gemma4", "ollama:gemma4", "local:", ":gemma4"):
        with pytest.raises(ValueError):
            parse(bad)


def test_provider_configured_and_extra_body():
    ep = Endpoints(
        local_url="http://127.0.0.1:11434/v1",
        local_api_key="",
        openrouter_url="https://openrouter.ai/api/v1",
        openrouter_api_key="",
    )
    assert configured(parse("local:x"), ep)
    assert not configured(parse("openrouter:x"), ep)  # no key
    keyed = Endpoints(ep.local_url, "", ep.openrouter_url, "k")
    assert configured(parse("openrouter:x"), keyed)
    assert extra_body(parse("openrouter:x")) == {"provider": {"require_parameters": True}}
    assert extra_body(parse("local:x")) is None
    assert extra_body(parse("local:x"), "none") == {
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    assert extra_body(parse("local:x"), "low") == {"reasoning_effort": "low"}
    assert extra_body(parse("openrouter:x"), "none") == {
        "provider": {"require_parameters": True},
        "reasoning_effort": "none",
    }
    assert extra_body(parse("openrouter:x"), "", ("fp8",)) == {
        "provider": {"require_parameters": True, "quantizations": ["fp8"], "sort": "price"}
    }
    assert extra_body(parse("local:x"), "", ("fp8",)) is None


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

    # _env_file=None: the developer's .env (models, keys) must not leak into this test.
    cfg = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        database_url="postgres://x",
        planning_agent_model="local:gemma4:12b-it-qat",
        redaction_agent_model="openrouter:qwen/qwen3-8b",
        redaction_agent_reasoning_effort="none",
    )
    ref = cfg.agent_model("planning")
    assert ref is not None and str(ref) == "local:gemma4:12b-it-qat"
    assert cfg.agent_ready("planning")
    # each agent has its own model: the sweep's is not the planner's, and needs its own key
    assert str(cfg.agent_model("redaction")) == "openrouter:qwen/qwen3-8b"
    assert not cfg.agent_ready("redaction")
    assert cfg.agent_reasoning_effort("redaction") == "none"
    assert cfg.agent_reasoning_effort("planning") == ""
    assert cfg.agent_model("conclusions") is None  # empty: that agent is unavailable
    assert not cfg.agent_ready("conclusions")
    with pytest.raises(ValidationError):
        Settings(database_url="postgres://x", conclusions_agent_model="gemma4")


class _CapturingCompletions:
    """Stands in for client.chat.completions and keeps the last request."""

    def __init__(self) -> None:
        self.request: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> ChatCompletion:
        self.request = kwargs
        return _completion('{"a": 1}')


def _capturing_client() -> tuple[Any, _CapturingCompletions]:
    completions = _CapturingCompletions()

    class Chat:
        pass

    class Client:
        chat = Chat()

    Client.chat.completions = completions  # type: ignore[attr-defined]
    return Client(), completions


async def test_a_local_model_reads_the_answers_schema_in_its_instructions():
    from agent.llm import Block, Request, Tool

    tool = Tool(
        "proponer", "d", {"avances": {"type": "array", "items": {"type": "string"}}}, ["avances"]
    )
    req = Request(
        system=[Block("Instrucciones.", cache=True)], prompt="x", tool=tool, max_tokens=10
    )
    for provider, shown in (("local", True), ("openrouter", False)):
        client, completions = _capturing_client()
        resp = await OpenAICompat(parse(f"{provider}:m"), client).generate(req)
        assert resp.input == {"a": 1}
        system = completions.request["messages"][0]["content"]
        assert system.startswith("Instrucciones.")
        assert ('"avances"' in system) is shown, provider
        # The schema still travels as response_format, which a server that honours it enforces.
        sent = completions.request["response_format"]["json_schema"]["schema"]
        assert sent == strict_schema(
            {"type": "object", "properties": tool.properties, "required": ["avances"]}
        )
        if shown:
            assert system.endswith(json.dumps(sent, ensure_ascii=False))


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
        "insert into voice_notes (id, session_id, student_id, class_id, teacher_id,"
        " duration_ms, audio, mime_type, byte_size) values (%s,%s,%s,%s,%s,5000,%s,'audio/mpeg',4)",
        (
            note,
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
    handler: Callable[[AsyncConnection, int, dict[str, Any]], Awaitable[None]],
    note: uuid.UUID,
) -> applog.OutcomeReport:
    from db import RequestCtx

    db = client.app.state.api.db
    report, token = applog.begin_outcome_report()
    try:
        async with db.user_tx(RequestCtx(request_id="job:test")) as conn:
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
