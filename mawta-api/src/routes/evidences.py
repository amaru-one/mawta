"""Evidence authoring and scores."""

from uuid import UUID

from starlette.requests import Request
from starlette.responses import Response

import authz
import domain
from errors import bad_request
from repo import events as events_repo
from repo import evidences as repo
from repo.terms import resolve_term
from web import (
    api_of,
    no_content,
    parse_uuid,
    path_uuid,
    read_body,
    tc_of,
    write_json,
)


async def handle_create_assessment(request: Request) -> Response:
    """File one piece of evidencia. student_id makes it evidence for that student alone; omitted,
    it is a column for the whole class. criterion_ids are the criterios it speaks to (at least
    one): evidence for the teacher's judgement, never rolled up into a level."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    req = await read_body(
        request,
        {
            "title": str,
            "kind": str,
            "value_scale": str,
            "max_score": float | None,
            "due_at": str | None,
            "term_id": str | None,
            "student_id": str | None,
            "criterion_ids": list[str],
        },
    )
    if not req["title"]:
        raise bad_request("title is required")
    if not domain.is_evidence_kind(req["kind"]):
        raise bad_request("kind must be produccion or actuacion")
    value_scale = req["value_scale"] or domain.VALUE_SCALE_NUMERIC
    max_score = req["max_score"]
    if value_scale == domain.VALUE_SCALE_NUMERIC:
        if max_score is None or max_score <= 0:
            raise bad_request("max_score is required and must be positive")
    elif value_scale == domain.VALUE_SCALE_ORDINAL:
        if max_score is not None:
            raise bad_request("max_score must be omitted for an ordinal assessment")
    else:
        raise bad_request("value_scale must be numeric or ordinal")

    term_param: UUID | None = None
    if req["term_id"] is not None:
        try:
            term_param = UUID(req["term_id"])
        except ValueError:
            term_param = (
                None  # deliberately lenient: an unparseable term_id falls back to the current term
            )

    student_id = None
    if req["student_id"]:
        student_id = parse_uuid(req["student_id"], "invalid student_id")

    if not req["criterion_ids"]:
        raise bad_request("criterion_ids needs at least one criterio")
    criterion_ids = [parse_uuid(raw, "invalid criterion_ids") for raw in req["criterion_ids"]]

    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        term = await resolve_term(conn, class_id, term_param)
        assert tc.teacher_id is not None
        assessment_id = await repo.create_assessment(
            conn,
            class_id=class_id,
            term_id=term["id"],
            teacher_id=tc.teacher_id,
            student_id=student_id,
            title=req["title"],
            kind=req["kind"],
            value_scale=value_scale,
            max_score=max_score,
            due_at=req["due_at"],
            criterion_ids=criterion_ids,
        )
        await events_repo.log_event(
            conn,
            "assessment.created",
            "assessment",
            assessment_id,
            student_id=student_id,
            class_id=class_id,
        )
    return write_json({"id": assessment_id}, 201)


async def handle_delete_assessment(request: Request) -> Response:
    """Soft-delete a piece of evidence created by mistake; its scores stay in the history."""
    api, tc = api_of(request), tc_of(request)
    assessment_id = path_uuid(request, "assessmentID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_assessment_access(conn, tc, assessment_id)
        deleted = await repo.delete_assessment(conn, assessment_id)
        await events_repo.log_event(
            conn,
            "assessment.deleted",
            "assessment",
            assessment_id,
            student_id=deleted["student_id"],
            class_id=deleted["class_id"],
        )
    return no_content()


async def handle_create_score(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    assessment_id = path_uuid(request, "assessmentID")
    req = await read_body(
        request,
        {"student_id": str, "status": str, "raw_value": float | None, "level": str | None},
    )
    student_id = parse_uuid(req["student_id"], "invalid student_id")
    status = req["status"] or domain.SCORE_GRADED
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_assessment_access(conn, tc, assessment_id)
        assert tc.teacher_id is not None
        score_id, class_id, _ = await repo.create_score(
            conn,
            assessment_id,
            student_id,
            tc.teacher_id,
            status,
            req["raw_value"],
            req["level"],
        )
        await events_repo.log_event(
            conn, "score.recorded", "score", score_id, student_id=student_id, class_id=class_id
        )
    return write_json({"id": score_id}, 201)


async def handle_correct_score(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    score_id = path_uuid(request, "scoreID")
    req = await read_body(
        request, {"raw_value": float | None, "level": str | None, "status": str | None}
    )
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_score_access(conn, tc, score_id)
        assert tc.teacher_id is not None
        new_id, student_id, class_id, _ = await repo.correct_score(
            conn, score_id, tc.teacher_id, req["raw_value"], req["level"], req["status"]
        )
        await events_repo.log_event(
            conn, "score.corrected", "score", new_id, student_id=student_id, class_id=class_id
        )
    return write_json({"id": new_id}, 201)
