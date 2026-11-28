"""Director feedback on Mawta answers (PUT/DELETE /messages/{id}/feedback), Langfuse score
forwarding, RLS isolation, and the continuous-review report (chat.review)."""

from contextlib import nullcontext
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from chat.review import build_report, collect_report, draft_cases, format_text, to_json
from chat.tracing import QuestionTrace
from db import sa_url
from tests.chat.conftest import ANA, BETO, FakeLLM, Session, text_turn, tool_turn
from tests.chat.test_ask import ask
from tests.conftest import Databases


class _FakeToolSpan:
    def result(self, result: Any, is_error: bool) -> None:
        return None


class _FakeQuestion:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id

    def tool(self, name: str, tool_input: Any):
        return nullcontext(_FakeToolSpan())

    def model_turn(self, turn: Any) -> None:
        return None

    def finish(
        self, *, answer: str, blocks: list[dict[str, Any]], latency_ms: int, stop_reason: str
    ) -> None:
        return None


class _RecordingTracer:
    def __init__(self, trace_id: str = "trace-abc-123") -> None:
        self.trace_id = trace_id
        self.scores: list[dict[str, Any]] = []

    def question(self, *, thread_key: str, user_id: str, question: str, system: str):
        q: QuestionTrace = _FakeQuestion(self.trace_id)
        return nullcontext(q)

    def score(
        self,
        trace_id: str,
        *,
        name: str,
        value: float,
        comment: str | None = None,
    ) -> None:
        self.scores.append({"trace_id": trace_id, "name": name, "value": value, "comment": comment})


async def test_feedback_roundtrip_and_langfuse_score(
    chat_client_for: Any, session: Session, fake_llm: FakeLLM
):
    tracer = _RecordingTracer("trace-feedback-1")
    client: httpx.AsyncClient = await chat_client_for(fake_llm, chat_tracer=tracer)
    me = await session(ANA)
    thread = (await client.post("/threads", headers=me)).json()
    fake_llm.script(tool_turn(), text_turn("Hay tres secciones."))

    await ask(client, me, thread["id"], "¿Qué secciones hay?")
    messages = (await client.get(f"/threads/{thread['id']}/messages", headers=me)).json()
    director_msg, mawta_msg = messages[0], messages[1]
    assert "feedback" not in director_msg
    assert mawta_msg["feedback"] is None

    # Vote positive
    res = await client.put(f"/messages/{mawta_msg['id']}/feedback", json={"rating": 1}, headers=me)
    assert res.status_code == 200
    assert res.json()["rating"] == 1
    assert tracer.scores[-1] == {
        "trace_id": "trace-feedback-1",
        "name": "director_feedback",
        "value": 1.0,
        "comment": None,
    }

    # Update to negative with reason and comment
    res = await client.put(
        f"/messages/{mawta_msg['id']}/feedback",
        json={
            "rating": -1,
            "reason": "falto_contexto",
            "comment": "  Faltó indicar los turnos  ",
        },
        headers=me,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["rating"] == -1
    assert body["reason"] == "falto_contexto"
    assert body["comment"] == "Faltó indicar los turnos"
    assert tracer.scores[-1] == {
        "trace_id": "trace-feedback-1",
        "name": "director_feedback",
        "value": 0.0,
        "comment": "[falto_contexto] Faltó indicar los turnos",
    }

    # Feedback persists in GET /threads/{id}/messages
    messages = (await client.get(f"/threads/{thread['id']}/messages", headers=me)).json()
    assert messages[1]["feedback"] == {
        "rating": -1,
        "reason": "falto_contexto",
        "comment": "Faltó indicar los turnos",
    }

    # Delete feedback
    deleted = await client.delete(f"/messages/{mawta_msg['id']}/feedback", headers=me)
    assert deleted.status_code == 204
    messages = (await client.get(f"/threads/{thread['id']}/messages", headers=me)).json()
    assert messages[1]["feedback"] is None

    # Cannot vote on a director's own question message
    bad_target = await client.put(
        f"/messages/{director_msg['id']}/feedback", json={"rating": 1}, headers=me
    )
    assert bad_target.status_code == 404


async def test_feedback_rejects_invalid_payloads_and_other_directors(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM
):
    ana = await session(ANA)
    beto = await session(BETO)
    thread = (await client.post("/threads", headers=ana)).json()
    fake_llm.script(tool_turn(), text_turn("Tres secciones."))
    await ask(client, ana, thread["id"], "¿Qué secciones hay?")
    mawta_id = (await client.get(f"/threads/{thread['id']}/messages", headers=ana)).json()[1]["id"]

    # Validation checks
    for bad in (
        {"rating": 0},
        {"rating": True},
        {"rating": -1, "reason": "inventado"},
        {"rating": -1, "comment": "x" * 501},
    ):
        res = await client.put(f"/messages/{mawta_id}/feedback", json=bad, headers=ana)
        assert res.status_code == 422

    # Another director cannot rate or delete feedback on Ana's answer
    assert (
        await client.put(f"/messages/{mawta_id}/feedback", json={"rating": -1}, headers=beto)
    ).status_code == 404
    assert (await client.delete(f"/messages/{mawta_id}/feedback", headers=beto)).status_code == 404


async def test_collect_report_aggregates_bank_and_feedback(
    client: httpx.AsyncClient, session: Session, fake_llm: FakeLLM, databases: Databases
):
    ana = await session(ANA)
    thread = (await client.post("/threads", headers=ana)).json()
    fake_llm.script(
        tool_turn(name="sin_herramienta", arguments='{"tema": "asistencia de 1A"}'),
        text_turn("Mawta aún no registra asistencia."),
    )
    await ask(client, ana, thread["id"], "¿Quiénes faltaron en 1A?")
    fake_llm.script(tool_turn(), text_turn("Hay tres secciones."))
    await ask(client, ana, thread["id"], "¿Qué secciones hay?")
    messages = (await client.get(f"/threads/{thread['id']}/messages", headers=ana)).json()
    answer_id = messages[-1]["id"]
    await client.put(
        f"/messages/{answer_id}/feedback",
        json={"rating": -1, "reason": "dato_incorrecto", "comment": "Faltó 1ro A"},
        headers=ana,
    )

    # Read with admin/owner privileges (chat-review runs as DB owner across directors)
    engine = create_async_engine(sa_url(databases.admin_url))
    try:
        async with engine.connect() as conn:
            report = await collect_report(conn, days=7)
    finally:
        await engine.dispose()
    assert report.totals["necesita_tool"] >= 1
    assert report.totals["feedback_negative"] >= 1
    assert any(t.topic == "asistencia de 1A" for t in report.missing_tools)
    neg = next(item for item in report.negative_feedback if item.message_id == answer_id)
    assert neg.question == "¿Qué secciones hay?"
    assert neg.reason == "dato_incorrecto"
    assert neg.comment == "Faltó 1ro A"
    assert neg.tools == ["datos_del_colegio"]


def test_build_report_formats_text_json_and_draft_cases():
    report = build_report(
        questions=[
            {
                "question": "¿Quién faltó ayer?",
                "status": "necesita_tool",
                "tool_name": "asistencia",
                "created_at": "2026-11-28T10:00:00Z",
            },
            {
                "question": "¿Cuántos en 1ro?",
                "status": "parcial",
                "tool_name": "resumen_de_niveles",
                "created_at": "2026-11-28T10:05:00Z",
            },
            {
                "question": "¿Qué secciones hay?",
                "status": "respondida",
                "tool_name": "datos_del_colegio",
                "created_at": "2026-11-28T10:10:00Z",
            },
        ],
        feedbacks=[
            {
                "message_id": "m-1",
                "rating": 1,
                "reason": None,
                "comment": None,
                "tool_calls": [{"name": "datos_del_colegio"}],
                "trace_id": "t-1",
                "question": "¿Qué secciones hay?",
                "created_at": "2026-11-28T10:11:00Z",
            },
            {
                "message_id": "m-2",
                "rating": -1,
                "reason": "grafico_innecesario",
                "comment": "Solo quería el total",
                "tool_calls": [{"name": "resumen_de_niveles"}],
                "trace_id": "t-2",
                "question": "¿Cuál es el área con más AD?",
                "created_at": "2026-11-28T10:12:00Z",
            },
        ],
        days=7,
    )
    assert report.totals == {
        "questions": 3,
        "respondida": 1,
        "necesita_tool": 1,
        "parcial": 1,
        "fuera_de_alcance": 0,
        "feedback_positive": 1,
        "feedback_negative": 1,
    }
    text_out = format_text(report)
    assert "asistencia (1)" in text_out
    assert "grafico_innecesario" in text_out
    assert "trace=t-2" in text_out
    assert "Solo quería el total" in text_out
    cases = draft_cases(report)
    assert len(cases) == 2
    assert "rev-cual-es-el-area-con" in cases[0]
    assert '"feedback_negative": 1' in to_json(report)
