"""✦ Generar con Mawta: the planning agent's generations and the descriptive-conclusions agent's.

Each route records a generation and queues the job that runs it, in one transaction, and answers
202 at once; the app polls GET /generations/{id}. What an agent proposes is saved pending, never
accepted on the teacher's behalf. The conclusion request is checked synchronously (a level must be
asserted and there must be enough graded evidence) so the teacher learns at once why Mawta cannot
help.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from starlette.requests import Request
from starlette.responses import Response

import authz
from agent import conclusions as conclusions_agent
from agent import planning as planning_agent
from agent import redaction as redaction_agent
from agent.enqueue import enqueue
from db import TenantCtx
from errors import AppError, bad_request
from repo import agent_generations as gens
from repo import conclusion_context as ctx_repo
from repo import events as events_repo
from repo import planning as planning_repo
from repo import planning_plan as plan_repo
from repo import redaction as redaction_repo
from repo.terms import resolve_term
from web import (
    api_of,
    body_field,
    parse_uuid,
    path_uuid,
    query_uuid,
    read_json,
    tc_of,
    write_json,
)

MAX_CONTEXT_RUNES = 300  # caps the teacher's event/context text; it is prompt input


def to_generation_response(gen: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": gen["id"], "kind": gen["kind"], "status": gen["status"]}
    if gen["status"] == gens.GENERATION_COMPLETED and gen["result"] is not None:
        out["result"] = gen["result"]
    if gen["error"] is not None:
        out["error"] = gen["error"]
    if gens.expired(gen, now or datetime.now(UTC)):
        out["status"] = gens.GENERATION_FAILED
        out["error"] = gens.EXPIRED_GENERATION_MESSAGE
    return out


def agent_available(request: Request) -> None:
    """503 agent_unavailable when no model is configured, so the app can offer manual creation
    only."""
    if not api_of(request).settings.anthropic_api_key.get_secret_value():
        raise AppError(
            503,
            "agent_unavailable",
            "Mawta no puede generar en este momento. Puedes escribirlo a mano.",
        )


async def start_generation(
    conn: AsyncConnection[DictRow], tc: TenantCtx, **fields
) -> dict[str, Any]:
    """Record a generation for the requesting teacher and queue its job, or return the one already
    running for the same target. `agent` says which agent serves it."""
    return await enqueue(conn, tc.tenant_id, requested_by=tc.teacher_id, **fields)


def accepted(gen: dict[str, Any]) -> Response:
    return write_json(to_generation_response(gen), 202)


async def _check_competencies_of_class(
    conn: AsyncConnection[DictRow], class_id: UUID, ids: list[UUID]
) -> None:
    if not ids:
        return
    cur = await plan_repo.get_curriculum(conn, class_id)
    of_class = {c["id"] for c in cur["competencies"]}
    if any(i not in of_class for i in ids):
        raise AppError(
            422, "competency_not_in_subject", "esa competencia no es del área de esta clase"
        )


# ---------------------------------------------------------------- planning --


async def handle_create_experience_proposal(request: Request) -> Response:
    """A proposal built from the teacher's idea. It is not saved as an experience: the app shows
    it for review and saves it with POST /classes/{classID}/experiences."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    raw = await read_json(request)
    term = body_field(raw, "term_id", str)
    idea = body_field(raw, "idea_text", str).strip()
    context = body_field(raw, "context_text", str).strip()
    competency_ids = body_field(raw, "competency_ids", list[str])
    if len(context) > MAX_CONTEXT_RUNES:
        raise AppError(
            400, "context_too_long", "el evento o contexto no puede pasar de 300 caracteres"
        )
    term_id = parse_uuid(term, "invalid term_id")
    if not idea:
        raise AppError(400, "missing_idea", "cuéntale a Mawta tu idea en una o dos frases")
    competencies = [parse_uuid(s, "invalid competency_ids") for s in competency_ids]
    agent_available(request)

    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        # The term must be one of the class's year (404 otherwise), and the chosen competencies of
        # its área.
        await plan_repo.resolve_plan_term(conn, class_id, term_id, datetime.now().date())
        await _check_competencies_of_class(conn, class_id, competencies)
        payload: dict[str, Any] = {"term_id": str(term_id), "idea_text": idea}
        if context:
            payload["context_text"] = context
        if competencies:
            payload["competency_ids"] = [str(c) for c in competencies]
        gen = await start_generation(
            conn,
            tc,
            agent=planning_agent.NAME,
            kind=planning_agent.KIND_EXPERIENCE,
            class_id=class_id,
            target_key=planning_agent.target_key(
                planning_agent.KIND_EXPERIENCE, class_id, None, UUID(int=0)
            ),
            input=payload,
        )
    return accepted(gen)


async def handle_generate_criteria(request: Request) -> Response:
    """Pending criteria for the capabilities of one competency that have none."""
    api, tc = api_of(request), tc_of(request)
    experience_id = path_uuid(request, "experienceID")
    raw = await read_json(request)
    competency_id = parse_uuid(body_field(raw, "competency_id", str), "invalid competency_id")
    agent_available(request)

    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_experience_access(conn, tc, experience_id)
        exp = await planning_repo.get_experience(conn, experience_id)
        if not any(c["id"] == competency_id for c in exp["competencies"]):
            raise AppError(
                422,
                "competency_not_in_experience",
                "esa competencia no está en esta experiencia",
            )
        gen = await start_generation(
            conn,
            tc,
            agent=planning_agent.NAME,
            kind=planning_agent.KIND_CRITERIA,
            class_id=class_id,
            experience_id=experience_id,
            target_key=planning_agent.target_key(
                planning_agent.KIND_CRITERIA, class_id, experience_id, competency_id
            ),
            input={"competency_id": str(competency_id)},
        )
    return accepted(gen)


async def _generate_for_experience(request: Request, kind: str) -> Response:
    api, tc = api_of(request), tc_of(request)
    experience_id = path_uuid(request, "experienceID")
    agent_available(request)
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_experience_access(conn, tc, experience_id)
        gen = await start_generation(
            conn,
            tc,
            agent=planning_agent.NAME,
            kind=kind,
            class_id=class_id,
            experience_id=experience_id,
            target_key=planning_agent.target_key(kind, class_id, experience_id, UUID(int=0)),
        )
    return accepted(gen)


async def handle_generate_evidences(request: Request) -> Response:
    """Pending evidences over the experience's criteria that no evidence observes."""
    return await _generate_for_experience(request, planning_agent.KIND_EVIDENCES)


async def handle_generate_sessions(request: Request) -> Response:
    """Pending session entries on the experience's class dates without one."""
    return await _generate_for_experience(request, planning_agent.KIND_SESSIONS)


async def handle_get_generation(request: Request) -> Response:
    """The state of a generation. A generation past its deadline reads as failed. error_detail
    never leaves the server."""
    api, tc = api_of(request), tc_of(request)
    generation_id = path_uuid(request, "generationID")
    async with api.db.tenant_tx(tc) as conn:
        gen = await gens.get_generation(conn, generation_id)
        await authz.require_class_access(conn, tc, gen["class_id"])
    return write_json(to_generation_response(gen))


# ------------------------------------------------------------- conclusions --


async def _conclusion_scope(
    conn: AsyncConnection[DictRow],
    tc: TenantCtx,
    class_id: UUID,
    student_id: UUID,
    competency_id: UUID,
    term_id: UUID | None,
) -> conclusions_agent.Scope:
    """Authorize a conclusion request and resolve its term: the teacher teaches the class, the
    student is on its roster, and the competency is one of the class's área."""
    await authz.require_class_access(conn, tc, class_id)
    await authz.require_student_on_roster(conn, tc, class_id, student_id)
    if not await ctx_repo.competency_in_class(conn, class_id, competency_id):
        raise AppError(404, "not_found", "esa competencia no es de esta clase")
    term = await resolve_term(conn, class_id, term_id)
    return conclusions_agent.Scope(class_id, student_id, competency_id, term["id"])


async def _queue_pending_sweeps(
    conn: AsyncConnection[DictRow], tc: TenantCtx, scope: conclusions_agent.Scope
) -> None:
    """Queue the name sweep of the student's transcribed notes in the term that were never swept."""
    ids = await redaction_repo.pending_voice_notes_for_student_term(
        conn, scope.class_id, scope.student_id, scope.term_id
    )
    for note_id in ids:
        note = await redaction_repo.get_voice_note_for_redaction(conn, note_id)
        await redaction_agent.queue(conn, tc.tenant_id, note, note["teacher_id"], False)


async def handle_generate_conclusion(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    student_id = path_uuid(request, "studentID")
    raw = await read_json(request)
    competency_id = parse_uuid(body_field(raw, "competency_id", str), "invalid competency_id")
    term_raw = body_field(raw, "term_id", str | None)
    term_param = parse_uuid(term_raw, "invalid term_id") if term_raw else None
    agent_available(request)

    thin: dict[str, Any] | None = None
    gen: dict[str, Any] | None = None
    async with api.db.tenant_tx(tc) as conn:
        scope = await _conclusion_scope(conn, tc, class_id, student_id, competency_id, term_param)
        # Notes recorded before the sweep existed, or while no model was configured, are swept
        # now. The proposal may start before they finish; it then says how many notes were still
        # in process.
        await _queue_pending_sweeps(conn, tc, scope)
        m = await conclusions_agent.gather(conn, scope)
        try:
            m.check()
        except AppError as exc:
            if exc is not conclusions_agent.ERR_INSUFFICIENT_EVIDENCE:
                raise
            # Not an error for the transaction: the sweeps queued above must still commit.
            thin = {
                "error": {"code": exc.code, "message": exc.message},
                "evidence": {
                    "graded_count": m.graded,
                    "minimum": conclusions_agent.MIN_GRADED_EVIDENCES,
                    "usable_voice_notes": len(m.voice_notes),
                    "discarded_voice_notes": [],
                },
            }
            if m.only_discarded_notes():
                thin["evidence"][
                    "discarded_voice_notes"
                ] = await ctx_repo.list_discarded_voice_notes(
                    conn, class_id, student_id, scope.term_id
                )
                assert tc.teacher_id is not None
                await events_repo.log_student_reads(
                    conn, [student_id], tc.teacher_id, class_id, None
                )
        else:
            gen = await start_generation(
                conn,
                tc,
                agent=conclusions_agent.NAME,
                kind=conclusions_agent.KIND_CONCLUSION,
                class_id=class_id,
                student_id=scope.student_id,
                competency_id=scope.competency_id,
                term_id=scope.term_id,
                target_key=conclusions_agent.target_key(scope),
                input={"competency_id": str(competency_id), "term_id": str(scope.term_id)},
            )
    if thin is not None:
        return write_json(thin, 422)
    assert gen is not None
    return accepted(gen)


async def handle_latest_conclusion_generation(request: Request) -> Response:
    """The latest conclusion generation for that competency and term, so a proposal survives a
    reload. {"generation": null} when there is none."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    student_id = path_uuid(request, "studentID")
    competency_id = query_uuid(request, "competency_id")
    if competency_id is None:
        raise bad_request("invalid competency_id")
    term_param = query_uuid(request, "term_id")
    out = None
    async with api.db.tenant_tx(tc) as conn:
        scope = await _conclusion_scope(conn, tc, class_id, student_id, competency_id, term_param)
        gen = await gens.latest_conclusion_generation(
            conn, scope.student_id, scope.competency_id, scope.term_id
        )
        if gen is not None:
            out = to_generation_response(gen)
            assert tc.teacher_id is not None
            await events_repo.log_student_reads(conn, [student_id], tc.teacher_id, class_id, None)
    return write_json({"generation": out})


async def handle_discarded_voice_notes(request: Request) -> Response:
    """The notes the sweep discarded for this student in the term, only when they are all the
    student has: that is the one case the teacher is asked to look at them (move or confirm).
    Otherwise {"voice_notes": []}."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    student_id = path_uuid(request, "studentID")
    term_param = query_uuid(request, "term_id")
    notes: list[dict[str, Any]] = []
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        await authz.require_student_on_roster(conn, tc, class_id, student_id)
        term = await resolve_term(conn, class_id, term_param)
        usable, counts = await ctx_repo.list_conclusion_voice_notes(
            conn, class_id, student_id, term["id"]
        )
        if not usable and counts["discarded"] > 0:
            notes = await ctx_repo.list_discarded_voice_notes(
                conn, class_id, student_id, term["id"]
            )
            assert tc.teacher_id is not None
            await events_repo.log_student_reads(conn, [student_id], tc.teacher_id, class_id, None)
    return write_json({"voice_notes": notes})
