"""Unit tests of the pieces around the agents: redaction replace, the conclusion guard, the
Anthropic client's schema/classification, the STT client and the transcribe handler."""

import base64
import json
import uuid

import httpx
import pytest

import applog
from agent.conclusions.guard import guard, name_words
from agent.llm import LLMError
from agent.llm.anthropic import classify, strict_schema
from agent.redaction.replace import Fragment, LocateError, attribution, locate, redact
from repo import redaction as rrepo
from stt import Client, SttError, SttPermanentError
from worker.handlers.transcribe import voice_note_transcribe


def frag(text, refers_to="other_person", key=""):
    return Fragment(text, refers_to, key)


# ------------------------------------------------------------- conclusion material --


def _material(standard):
    from agent.conclusions import Material, Scope

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
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {}}}},
    }
    before = json.dumps(schema)
    out = strict_schema(schema)
    assert out["additionalProperties"] is False
    assert out["properties"]["items"]["items"]["additionalProperties"] is False
    assert json.dumps(schema) == before


def test_classify_provider_errors():
    import anthropic
    import httpx2  # the HTTP client the anthropic SDK is typed against

    def status(code: int) -> anthropic.APIStatusError:
        resp = httpx2.Response(code, request=httpx2.Request("POST", "https://x"))
        return anthropic.APIStatusError("boom", response=resp, body=None)

    assert classify(status(429)).permanent is False
    assert classify(status(529)).permanent is False
    assert classify(status(400)).permanent is True
    assert classify(RuntimeError("net")).permanent is False
    assert isinstance(classify(status(400)), LLMError)


# ------------------------------------------------------------------- stt --


def make_stt(handler, key="k"):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Client(key, "m", endpoint="https://stt.test/x", http=http)


async def test_stt_success_reports_provider_usage_and_never_the_audio():
    seen = {}

    def handler(request):
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
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text, self.error = text, error

    async def transcribe(self, audio_mp3: bytes) -> str:
        if self.error:
            raise self.error
        return self.text


async def insert_note(admin, audio=b"fake"):
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


async def run_handler(client, handler, note):
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


async def note_state(admin, note):
    cur = await admin.execute(
        "select transcription_status, transcript from voice_notes where id = %s", (note,)
    )
    return await cur.fetchone()


async def test_transcribe_success_saves_the_transcript(client, admin):
    note = await insert_note(admin)
    try:
        await run_handler(client, voice_note_transcribe(FakeTranscriber("prueba")), note)
        row = await note_state(admin, note)
        assert (row["transcription_status"], row["transcript"]) == ("completed", "prueba")
    finally:
        await admin.execute("delete from voice_notes where id = %s", (note,))


async def test_transcribe_permanent_failure_is_recorded_not_retried(client, admin):
    note = await insert_note(admin)
    try:
        handler = voice_note_transcribe(FakeTranscriber(error=SttPermanentError("no key")))
        report = await run_handler(client, handler, note)
        assert report.outcome == applog.OUTCOME_PERMANENT_FAILURE
        row = await note_state(admin, note)
        assert row["transcription_status"] == "failed" and row["transcript"] is None
    finally:
        await admin.execute("delete from voice_notes where id = %s", (note,))


async def test_transcribe_transient_error_propagates_and_discarded_note_is_skipped(client, admin):
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
