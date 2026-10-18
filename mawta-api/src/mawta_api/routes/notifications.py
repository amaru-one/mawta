"""Notifications and the profile screen."""

from datetime import datetime

from starlette.requests import Request
from starlette.responses import Response

from mawta_api.errors import bad_request
from mawta_api.http import api_of, path_uuid, query_int, query_uuid, tc_of, write_json
from mawta_api.repo import profile as profile_repo
from mawta_api.repo import sessions as repo
from mawta_api.repo.terms import resolve_term
from mawta_api.routes.screens import resolve_date


async def handle_list_notifications(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    kind = request.query_params.get("kind", "")
    limit = query_int(request, "limit", 50)
    before = None
    if raw := request.query_params.get("before", ""):
        try:
            before = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise bad_request("invalid before timestamp") from None
        if before.tzinfo is None:  # RFC 3339 requires an offset
            raise bad_request("invalid before timestamp")
    async with api.db.tenant_tx(tc) as conn:
        assert tc.teacher_id is not None
        notifications = await repo.list_notifications(conn, tc.teacher_id, kind, limit, before)
    return write_json({"notifications": notifications})


async def handle_mark_notification_read(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    notification_id = path_uuid(request, "notificationID")
    async with api.db.tenant_tx(tc) as conn:
        assert tc.teacher_id is not None
        await repo.mark_notification_read(conn, notification_id, tc.teacher_id)
    return write_json({"ok": True})


async def handle_mark_all_notifications_read(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    async with api.db.tenant_tx(tc) as conn:
        assert tc.teacher_id is not None
        n = await repo.mark_all_notifications_read(conn, tc.teacher_id)
    return write_json({"marked_read": n})


async def handle_profile(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    term_id = query_uuid(request, "term_id")
    async with api.db.tenant_tx(tc) as conn:
        today = await resolve_date(conn, tc, request.query_params.get("date", ""))
        term = await resolve_term(conn, None, term_id)
        assert tc.teacher_id is not None
        resp = await profile_repo.get_profile(conn, tc.teacher_id, term, today)
    return write_json(resp)
