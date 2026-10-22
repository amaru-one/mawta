"""Term planning: "Tu trimestre", the curriculum and calendar it is planned against, and the
learning experiences themselves. The contract is
docs/api-planificacion.md. Every route reaches a class (directly or through an experience,
criterion or evidence) and is guarded by require_class_access on that class.

Each write follows one shape: parse the path and body (ids as strings, parsed here so a bad one
is a 400 naming the field), then in one tenant transaction guard the class, write, log the
event, and answer with the written object as the experience read shows it.
"""

from datetime import date
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from starlette.requests import Request
from starlette.responses import Response

import authz
from errors import bad_request
from repo import events as events_repo
from repo import planning as repo
from repo import planning_outline as outline
from repo import planning_plan as plan_repo
from repo.home import tenant_today
from repo.planning_sync import heal_class_plan
from web import (
    api_of,
    body_field,
    no_content,
    parse_uuid,
    path_uuid,
    query_uuid,
    read_json,
    tc_of,
    write_json,
)

MAX_CONTEXT_RUNES = 300  # caps the teacher's event/context text; it is prompt input


def parse_plan_date(value: str, message: str) -> date:
    """Exactly YYYY-MM-DD."""
    try:
        if len(value) != 10:
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise bad_request(message) from None


def _uuid_list(field: str, raw: list[str]) -> list[UUID]:
    return [parse_uuid(s, f"invalid {field}") for s in raw]


def _optional_date(field: str, raw: str | None) -> date | None:
    if raw is None:
        return None
    return parse_plan_date(raw, f"{field} must be a YYYY-MM-DD date")


async def _log(
    conn: AsyncConnection[DictRow], action: str, entity_type: str, entity_id: UUID, class_id: UUID
) -> None:
    await events_repo.log_event(conn, action, entity_type, entity_id, class_id=class_id)


# ------------------------------------------------------------------ reads --


async def handle_class_plan(request: Request) -> Response:
    """ "Tu trimestre". Without term_id, the term that contains today, or else the next one."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    term_id = query_uuid(request, "term_id")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        today = await tenant_today(conn, tc.tenant_id)
        term = await plan_repo.resolve_plan_term(conn, class_id, term_id, today)
        await heal_class_plan(conn, class_id)
        plan = await plan_repo.get_plan(conn, class_id, term)
    return write_json(plan)


async def handle_class_curriculum(request: Request) -> Response:
    """The competencies of the class's área, each with its capabilities, the standard of the
    class's cycle and the performances of the class's grade."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        out = await plan_repo.get_curriculum(conn, class_id)
    return write_json(out)


async def handle_class_calendar(request: Request) -> Response:
    """Class dates and non-teaching days in a range at most one term long."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    from_ = parse_plan_date(request.query_params.get("from", ""), "from must be a YYYY-MM-DD date")
    to = parse_plan_date(request.query_params.get("to", ""), "to must be a YYYY-MM-DD date")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        out = await plan_repo.get_calendar(conn, class_id, from_, to)
    return write_json(out)


async def handle_get_experience(request: Request) -> Response:
    """The whole experience, with the warnings the summary screen shows."""
    api, tc = api_of(request), tc_of(request)
    experience_id = path_uuid(request, "experienceID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_experience_access(conn, tc, experience_id)
        out = await repo.get_experience(conn, experience_id)
    return write_json(out)


# ------------------------------------------------------------- experience --


async def handle_create_experience(request: Request) -> Response:
    """The first step of the flow: the experience is saved as a draft and every later step
    writes to it (decision 1 of the contract)."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    raw = await read_json(request)
    body = {
        "term_id": body_field(raw, "term_id", str),
        "title": body_field(raw, "title", str),
        "idea_text": body_field(raw, "idea_text", str),
        "situation_text": body_field(raw, "situation_text", str | None),
        "context_text": body_field(raw, "context_text", str | None),
        "starts_on": body_field(raw, "starts_on", str),
        "ends_on": body_field(raw, "ends_on", str),
        "competency_ids": body_field(raw, "competency_ids", list[str]),
    }
    if body["context_text"] is not None and len(body["context_text"]) > MAX_CONTEXT_RUNES:
        raise bad_request("context_text must be at most 300 characters")
    term_id = parse_uuid(body["term_id"], "invalid term_id")
    starts_on = parse_plan_date(body["starts_on"], "starts_on must be a YYYY-MM-DD date")
    ends_on = parse_plan_date(body["ends_on"], "ends_on must be a YYYY-MM-DD date")
    competency_ids = _uuid_list("competency_ids", body["competency_ids"])

    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        experience_id = await repo.create_experience(
            conn,
            class_id,
            term_id=term_id,
            title=body["title"],
            idea_text=body["idea_text"],
            situation_text=body["situation_text"],
            context_text=body["context_text"],
            starts_on=starts_on,
            ends_on=ends_on,
            competency_ids=competency_ids,
        )
        await _log(conn, "experience.created", "learning_experience", experience_id, class_id)
        out = await repo.get_experience(conn, experience_id)
    return write_json(out, 201)


async def handle_update_experience(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    experience_id = path_uuid(request, "experienceID")
    raw = await read_json(request)
    title = body_field(raw, "title", str | None)
    situation = body_field(raw, "situation_text", str | None)
    starts = body_field(raw, "starts_on", str | None)
    ends = body_field(raw, "ends_on", str | None)
    competency_ids = body_field(raw, "competency_ids", list[str] | None)

    patch: dict[str, Any] = {}
    if title is not None:
        patch["title"] = title
    if situation is not None:
        patch["situation_text"] = situation
    if (d := _optional_date("starts_on", starts)) is not None:
        patch["starts_on"] = d
    if (d := _optional_date("ends_on", ends)) is not None:
        patch["ends_on"] = d
    if competency_ids is not None:
        patch["competency_ids"] = _uuid_list("competency_ids", competency_ids)

    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_experience_access(conn, tc, experience_id)
        await repo.update_experience(conn, experience_id, patch)
        await _log(conn, "experience.updated", "learning_experience", experience_id, class_id)
        out = await repo.get_experience(conn, experience_id)
    return write_json(out)


async def handle_confirm_experience(request: Request) -> Response:
    """ "Revisar y guardar". Answers with the experience and its warnings, which never block."""
    api, tc = api_of(request), tc_of(request)
    experience_id = path_uuid(request, "experienceID")
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_experience_access(conn, tc, experience_id)
        await repo.confirm_experience(conn, experience_id)
        await _log(conn, "experience.confirmed", "learning_experience", experience_id, class_id)
        out = await repo.get_experience(conn, experience_id)
    return write_json(out)


async def handle_delete_experience(request: Request) -> Response:
    """Its criteria, evidences and session outline go with it."""
    api, tc = api_of(request), tc_of(request)
    experience_id = path_uuid(request, "experienceID")
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_experience_access(conn, tc, experience_id)
        await repo.delete_experience(conn, experience_id)
        await _log(conn, "experience.deleted", "learning_experience", experience_id, class_id)
    return no_content()


# --------------------------------------------------------------- criteria --


async def handle_create_planned_criterion(request: Request) -> Response:
    """A criterion the teacher writes from the cycle standard, looking at one or more
    capabilities of its competency. A grade performance is optional."""
    api, tc = api_of(request), tc_of(request)
    experience_id = path_uuid(request, "experienceID")
    raw = await read_json(request)
    competency = body_field(raw, "competency_id", str)
    description = body_field(raw, "description", str)
    capability_ids = body_field(raw, "capability_ids", list[str])
    performance = body_field(raw, "performance_id", str | None)
    competency_id = parse_uuid(competency, "invalid competency_id")
    performance_id = (
        parse_uuid(performance, "invalid performance_id") if performance is not None else None
    )
    inp = {
        "competency_id": competency_id,
        "description": description,
        "capability_ids": _uuid_list("capability_ids", capability_ids),
        "performance_id": performance_id,
    }
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_experience_access(conn, tc, experience_id)
        criterion_id = await repo.create_planned_criterion(conn, experience_id, inp)
        await _log(conn, "criterion.created", "evaluation_criterion", criterion_id, class_id)
        out = await repo.get_planned_criterion(conn, criterion_id)
    return write_json(out, 201)


async def handle_update_planned_criterion(request: Request) -> Response:
    """Editing a Mawta proposal also accepts it."""
    api, tc = api_of(request), tc_of(request)
    criterion_id = path_uuid(request, "criterionID")
    raw = await read_json(request)
    description = body_field(raw, "description", str | None)
    capability_ids = body_field(raw, "capability_ids", list[str] | None)
    performance = body_field(raw, "performance_id", str | None)

    patch: dict[str, Any] = {}
    if description is not None:
        patch["description"] = description
    if capability_ids is not None:
        patch["capability_ids"] = _uuid_list("capability_ids", capability_ids)
    if "performance_id" in raw:  # present, even when null: null removes the performance
        patch["performance_id"] = (
            parse_uuid(performance, "invalid performance_id") if performance is not None else None
        )

    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_planned_criterion_access(conn, tc, criterion_id)
        await repo.update_planned_criterion(conn, criterion_id, patch)
        await _log(conn, "criterion.updated", "evaluation_criterion", criterion_id, class_id)
        out = await repo.get_planned_criterion(conn, criterion_id)
    return write_json(out)


async def handle_accept_planned_criterion(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    criterion_id = path_uuid(request, "criterionID")
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_planned_criterion_access(conn, tc, criterion_id)
        await repo.accept_planned_criterion(conn, criterion_id)
        await _log(conn, "criterion.accepted", "evaluation_criterion", criterion_id, class_id)
        out = await repo.get_planned_criterion(conn, criterion_id)
    return write_json(out)


# -------------------------------------------------------------- evidences --


async def handle_create_planned_evidence(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    experience_id = path_uuid(request, "experienceID")
    raw = await read_json(request)
    inp = {
        "name": body_field(raw, "name", str),
        "kind": body_field(raw, "kind", str),
        "value_scale": body_field(raw, "value_scale", str),
        "max_score": body_field(raw, "max_score", float | None),
    }
    inp["criterion_ids"] = _uuid_list("criterion_ids", body_field(raw, "criterion_ids", list[str]))
    inp["session_date"] = _optional_date(
        "session_date", body_field(raw, "session_date", str | None)
    )
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_experience_access(conn, tc, experience_id)
        evidence_id = await repo.create_planned_evidence(conn, experience_id, inp)
        await _log(conn, "planned_evidence.created", "planned_evidence", evidence_id, class_id)
        out = await outline.get_planned_evidence(conn, evidence_id)
    return write_json(out, 201)


async def handle_update_planned_evidence(request: Request) -> Response:
    """ "session_date": null takes the evidence out of its session; leaving the key out keeps it
    where it is. Editing a proposal also accepts it."""
    api, tc = api_of(request), tc_of(request)
    evidence_id = path_uuid(request, "evidenceID")
    raw = await read_json(request)
    patch: dict[str, Any] = {}
    for name in ("name", "kind", "value_scale"):
        if (value := body_field(raw, name, str | None)) is not None:
            patch[name] = value
    if (max_score := body_field(raw, "max_score", float | None)) is not None:
        patch["max_score"] = max_score
    criterion_ids = body_field(raw, "criterion_ids", list[str] | None)
    session_date = body_field(raw, "session_date", str | None)
    if criterion_ids is not None:
        patch["criterion_ids"] = _uuid_list("criterion_ids", criterion_ids)
    if "session_date" in raw:
        patch["session_date"] = _optional_date("session_date", session_date)

    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_evidence_access(conn, tc, evidence_id)
        await outline.update_planned_evidence(conn, evidence_id, patch)
        await _log(conn, "planned_evidence.updated", "planned_evidence", evidence_id, class_id)
        out = await outline.get_planned_evidence(conn, evidence_id)
    return write_json(out)


async def handle_accept_planned_evidence(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    evidence_id = path_uuid(request, "evidenceID")
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_evidence_access(conn, tc, evidence_id)
        await outline.accept_planned_evidence(conn, evidence_id)
        await _log(conn, "planned_evidence.accepted", "planned_evidence", evidence_id, class_id)
        out = await outline.get_planned_evidence(conn, evidence_id)
    return write_json(out)


async def handle_delete_planned_evidence(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    evidence_id = path_uuid(request, "evidenceID")
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_evidence_access(conn, tc, evidence_id)
        await outline.delete_planned_evidence(conn, evidence_id)
        await _log(conn, "planned_evidence.deleted", "planned_evidence", evidence_id, class_id)
    return no_content()


# ----------------------------------------------------------- session outline --


def _session_path(request: Request) -> tuple[UUID, date]:
    experience_id = path_uuid(request, "experienceID")
    on = parse_plan_date(request.path_params["date"], "date must be a YYYY-MM-DD date")
    return experience_id, on


async def handle_put_session_entry(request: Request) -> Response:
    """Creates or replaces that date's entry, and accepts it."""
    api, tc = api_of(request), tc_of(request)
    experience_id, on = _session_path(request)
    raw = await read_json(request)
    title = body_field(raw, "title", str)
    topics = body_field(raw, "topics", str | None)
    evidence = body_field(raw, "planned_evidence_id", str | None)
    evidence_id = (
        parse_uuid(evidence, "invalid planned_evidence_id") if evidence is not None else None
    )
    inp = {"title": title, "topics": topics, "planned_evidence_id": evidence_id}
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_experience_access(conn, tc, experience_id)
        await outline.put_session_entry(conn, experience_id, on, inp)
        await _log(conn, "session_outline.saved", "learning_experience", experience_id, class_id)
        out = await outline.get_session_entry(conn, experience_id, on)
    return write_json(out)


async def handle_accept_session_entry(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    experience_id, on = _session_path(request)
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_experience_access(conn, tc, experience_id)
        await outline.accept_session_entry(conn, experience_id, on)
        await _log(conn, "session_outline.accepted", "learning_experience", experience_id, class_id)
        out = await outline.get_session_entry(conn, experience_id, on)
    return write_json(out)


async def handle_delete_session_entry(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    experience_id, on = _session_path(request)
    async with api.db.tenant_tx(tc) as conn:
        class_id = await authz.require_experience_access(conn, tc, experience_id)
        await outline.delete_session_entry(conn, experience_id, on)
        await _log(conn, "session_outline.deleted", "learning_experience", experience_id, class_id)
    return no_content()
