"""Home, class dashboard, class list and a student's evidence."""

from datetime import date

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from starlette.requests import Request
from starlette.responses import Response

import authz
from db import TenantCtx
from errors import bad_request
from repo import classes as classes_repo
from repo import events as events_repo
from repo import home as home_repo
from repo import students as students_repo
from repo.planning_sync import heal_class_plan
from repo.terms import resolve_term
from web import (
    api_of,
    parse_date,
    parse_uuid,
    path_uuid,
    query_uuid,
    tc_of,
    write_json,
)


async def resolve_date(conn: AsyncConnection[DictRow], tc: TenantCtx, date_param: str) -> date:
    """?date=YYYY-MM-DD, defaulting to "today" in the tenant's timezone when absent."""
    if date_param:
        return parse_date(date_param)
    return await home_repo.tenant_today(conn, tc.tenant_id)


async def handle_home(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    async with api.db.tenant_tx(tc) as conn:
        d = await resolve_date(conn, tc, request.query_params.get("date", ""))
        assert tc.teacher_id is not None
        resp = await home_repo.get_home(conn, tc.teacher_id, d)
    return write_json(resp)


async def handle_class_dashboard(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    term_id = query_uuid(request, "term_id")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        today = await resolve_date(conn, tc, request.query_params.get("date", ""))
        term = await resolve_term(conn, class_id, term_id)
        await heal_class_plan(conn, class_id)
        dashboard = await classes_repo.get_class_dashboard(conn, class_id, term, today)
    return write_json(dashboard)


def _competency_id_param(request: Request):
    """The optional ?competency_id=. Absent is legitimate: a class whose área has no
    competencias configured still has a roster."""
    raw = request.query_params.get("competency_id", "").strip()
    if not raw:
        return None
    return parse_uuid(raw, "invalid competency_id")


async def handle_class_students(request: Request) -> Response:
    """The class roster with each student's nivel de logro in one competencia and the number
    of pieces of evidencia behind it. A null level means the teacher has not judged this
    competencia for this student yet (RVM 048-2024, 5.1.2.2), never a C."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    competency_id = _competency_id_param(request)
    term_id = query_uuid(request, "term_id")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        term = await resolve_term(conn, class_id, term_id)
        today = await home_repo.tenant_today(conn, tc.tenant_id)
        students = await students_repo.list_class_students(
            conn, class_id, competency_id, term["id"], today
        )
        assert tc.teacher_id is not None
        await events_repo.log_student_reads(
            conn, [s["student_id"] for s in students], tc.teacher_id, class_id, None
        )
    return write_json({"students": students})


async def handle_student_evidence(request: Request) -> Response:
    """The period's evidencia for one student, narrowed to one competencia through the
    criterio tags. Nothing is aggregated and nothing suggests a level (RVM 094-2020, 5.1.1.3)."""
    api, tc = api_of(request), tc_of(request)
    class_id = path_uuid(request, "classID")
    student_id = path_uuid(request, "studentID")
    competency_id = _competency_id_param(request)
    term_id = query_uuid(request, "term_id")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_class_access(conn, tc, class_id)
        await authz.require_student_on_roster(conn, tc, class_id, student_id)
        term = await resolve_term(conn, class_id, term_id)
        evidence = await students_repo.list_student_evidence(
            conn, class_id, student_id, competency_id, term["id"]
        )
        assert tc.teacher_id is not None
        await events_repo.log_student_reads(conn, [student_id], tc.teacher_id, class_id, None)
    return write_json({"evidence": evidence})


_ = bad_request
