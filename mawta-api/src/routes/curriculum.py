"""Niveles de logro, conclusiones, criterios y capacidades."""

from uuid import UUID

from starlette.requests import Request
from starlette.responses import Response

import authz
import domain
from errors import bad_request
from repo import competencies as repo
from repo import criteria as criteria_repo
from repo import events as events_repo
from repo.terms import resolve_term
from web import (
    api_of,
    no_content,
    parse_uuid,
    path_uuid,
    query_uuid,
    read_body,
    tc_of,
    write_json,
)


def _term_param(raw: str | None) -> UUID | None:
    """Deliberately lenient: an unparseable term_id falls back to the current term."""
    if raw is None:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


async def handle_student_competencies(request: Request) -> Response:
    """The registration screen for niveles de logro: every competency of the área, the level
    the teacher has asserted (if any), and whether a conclusión descriptiva is mandatory."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    student_id = path_uuid(request, "studentID")
    term_id = query_uuid(request, "term_id")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        await authz.require_student_on_roster(conn, tc, class_id, student_id)
        term = await resolve_term(conn, class_id, term_id)
        rows = await repo.list_class_competency_levels(conn, class_id, student_id, term["id"])
        assert tc.teacher_id is not None
        await events_repo.log_student_reads(conn, [student_id], tc.teacher_id, class_id, None)
    return write_json({"competencies": rows})


async def handle_assert_competency_level(request: Request) -> Response:
    """Record the teacher's nivel de logro: the only writer of the official record."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    student_id = path_uuid(request, "studentID")
    req = await read_body(
        request,
        {"competency_id": str, "level": str, "note": str | None, "term_id": str | None},
        "invalid body",
    )
    competency_id = parse_uuid(req["competency_id"], "invalid competency_id")
    level = req["level"].strip().upper()
    if level not in (domain.LEVEL_AD, domain.LEVEL_A, domain.LEVEL_B, domain.LEVEL_C):
        raise bad_request("level must be AD, A, B or C")
    term_param = _term_param(req["term_id"])

    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        await authz.require_student_on_roster(conn, tc, class_id, student_id)
        term = await resolve_term(conn, class_id, term_param)
        assert tc.teacher_id is not None
        level_id = await repo.assert_competency_level(
            conn,
            class_id,
            student_id,
            competency_id,
            term["id"],
            tc.teacher_id,
            level,
            req["note"],
        )
        await events_repo.log_event(
            conn,
            "competency_level.asserted",
            "competency_term_level",
            level_id,
            {"level": level, "competency_id": str(competency_id)},
            student_id,
            class_id,
        )
    return write_json({"id": level_id, "level": level}, 201)


async def handle_upsert_conclusion(request: Request) -> Response:
    """Write a conclusión descriptiva. Why it is mandatory (or not) is decided server-side from
    the student's live level."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    student_id = path_uuid(request, "studentID")
    req = await read_body(
        request,
        {
            "competency_id": str,
            "body": str,
            "status": str,
            "term_id": str | None,
            "generation_id": str | None,
        },
        "invalid body",
    )
    competency_id = parse_uuid(req["competency_id"], "invalid competency_id")
    if not req["body"].strip():
        raise bad_request("body is required")
    status = req["status"] or domain.CONCLUSION_DRAFT
    if status not in (domain.CONCLUSION_DRAFT, domain.CONCLUSION_FINAL):
        raise bad_request("status must be draft or final")
    term_param = _term_param(req["term_id"])
    generation_id = None
    if req["generation_id"]:
        generation_id = parse_uuid(req["generation_id"], "invalid generation_id")

    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        await authz.require_student_on_roster(conn, tc, class_id, student_id)
        term = await resolve_term(conn, class_id, term_param)
        assert tc.teacher_id is not None
        conclusion_id = await repo.upsert_conclusion(
            conn,
            class_id,
            student_id,
            competency_id,
            term["id"],
            tc.teacher_id,
            req["body"].strip(),
            status,
            generation_id,
        )
        await events_repo.log_event(
            conn,
            "conclusion.written",
            "descriptive_conclusion",
            conclusion_id,
            {
                "status": status,
                "competency_id": str(competency_id),
                "generation_id": str(generation_id) if generation_id else None,
            },
            student_id,
            class_id,
        )
    return write_json({"id": conclusion_id, "status": status}, 201)


async def handle_class_criteria(request: Request) -> Response:
    """Every competencia of the class's área with the criterios the teacher has written for it.
    A competencia with no criterios comes back with an empty list rather than being omitted."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        rows = await criteria_repo.list_class_criteria(conn, class_id)
    return write_json({"competencies": rows})


async def handle_evidence_criteria(request: Request) -> Response:
    """The criterios "Añadir evidencia" offers: the accepted criterios of the class's planned
    experiencias in the term, each carrying the experiencia it was written for."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    term_id = query_uuid(request, "term_id")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        term = await resolve_term(conn, class_id, term_id)
        rows = await criteria_repo.list_evidence_criteria(conn, class_id, term["id"])
    return write_json({"competencies": rows})


async def handle_competency_capabilities(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    competency_id = path_uuid(request, "competencyID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_competency_access(conn, tc, competency_id)
        rows = await criteria_repo.list_competency_capabilities(conn, competency_id)
    return write_json({"capabilities": rows})


async def handle_create_capability(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    competency_id = path_uuid(request, "competencyID")
    req = await read_body(request, {"code": str, "name": str}, "invalid body")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_competency_access(conn, tc, competency_id)
        capability_id = await criteria_repo.create_capability(
            conn, competency_id, req["code"], req["name"]
        )
        await events_repo.log_event(conn, "capability.created", "capability", capability_id)
    return write_json({"id": capability_id}, 201)


async def handle_delete_criterion(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    criterion_id = path_uuid(request, "criterionID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_criterion_access(conn, tc, criterion_id)
        await criteria_repo.delete_criterion(conn, criterion_id)
        await events_repo.log_event(conn, "criterion.deleted", "evaluation_criterion", criterion_id)
    return no_content()
