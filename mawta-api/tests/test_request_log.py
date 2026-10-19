"""The request id and the one completion event per request."""

import io
import json
import logging

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from mawta_api import applog
from mawta_api.http import RequestLogMiddleware, handle


def build(capture: bool = False):
    stream = io.StringIO()
    logger = applog.new_json_logger(logging.INFO, stream)

    async def ok(request):
        return PlainTextResponse("ok")

    pattern = "/api/v1/classes/{classID}/students"
    app = Starlette(
        routes=[Route(pattern, handle(pattern, ok))],
        middleware=[Middleware(RequestLogMiddleware, logger=logger, capture=capture)],
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, stream


def last_entry(stream: io.StringIO) -> dict:
    return json.loads(stream.getvalue().strip().splitlines()[-1])


async def test_completion_event_has_structured_fields():
    client, stream = build()
    resp = await client.get("/api/v1/classes/abc/students")
    assert resp.status_code == 200
    entry = last_entry(stream)
    assert entry["service"] == "mawta-server"
    assert entry["event"] == "http.request"
    assert entry["method"] == "GET"
    assert entry["status"] == 200
    assert "duration_ms" in entry and entry["request_id"]
    # The pattern, not the path with parameter values in it.
    assert entry["route"] == "/api/v1/classes/{classID}/students"
    assert entry["request_capture"] == entry["response_capture"] == "disabled"


async def test_x_request_id_is_propagated():
    client, stream = build()
    resp = await client.get("/api/v1/classes/abc/students", headers={"X-Request-ID": "custom"})
    assert resp.headers["x-request-id"] == "custom"
    assert last_entry(stream)["request_id"] == "custom"


async def test_unmatched_route_falls_back_to_the_path():
    client, stream = build()
    resp = await client.get("/api/v1/unknown/path")
    assert resp.status_code == 404
    assert last_entry(stream)["route"] == "/api/v1/unknown/path"


def test_capture_policy():
    policy = applog.CapturePolicy(enabled=True)
    route = "/api/v1/classes/{classID}/assessments"
    body = json.dumps(
        {"kind": "produccion", "title": "secret words", "value_scale": "numeric"}
    ).encode()
    captured = policy.capture_request_body(route, "application/json", body)
    assert captured.status == applog.CAPTURE_CAPTURED
    assert captured.value == {"kind": "produccion", "value_scale": "numeric"}

    omitted = policy.capture_request_body("/api/v1/auth/login", "application/json", body)
    assert omitted.status == applog.CAPTURE_OMITTED
    assert policy.capture_request_body(route, "multipart/form-data", body).status == "omitted"
    assert policy.capture_request_body(route, "application/json", b"").status == "empty"
    assert policy.capture_request_body(route, "application/json", b"{bad").status == "invalid_json"
    big = b"x" * (applog.MAX_BODY_BYTES + 1)
    assert policy.capture_request_body(route, "application/json", big).status == "too_large"
    assert (
        applog.CapturePolicy(enabled=False)
        .capture_request_body(route, "application/json", body)
        .status
        == "disabled"
    )
