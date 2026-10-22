"""HTTP plumbing: JSON responses and the error envelope, request helpers, the
request-id / request-logging middleware and the route-wrapping decorators that
stand in for chi's middleware groups.

Handlers are `async def h(request) -> Response`. They read the tenant context
from `request.state.tc` and the shared services from `request.app.state.api`.
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, TypedDict, get_args

import psycopg
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

import applog
import auth as authpkg
import domain
import jsonutil
from chattoken import Issuer
from db import Database, TenantCtx
from errors import AppError, bad_request, map_error
from repo import auth as auth_repo
from settings import Settings

Handler = Callable[[Request], Awaitable[Response]]


@dataclass
class Api:
    """The shared services every handler needs ."""

    db: Database
    settings: Settings
    logger: logging.Logger
    # None when no chat signing key is configured.
    chat_tokens: Issuer | None = None


def api_of(request: Request) -> Api:
    return request.app.state.api


def tc_of(request: Request) -> TenantCtx:
    return request.state.tc


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------


dumps = jsonutil.dumps
rfc3339 = jsonutil.rfc3339


class JSONResp(Response):
    media_type = "application/json; charset=utf-8"

    def __init__(
        self, content: Any = None, status_code: int = 200, headers: dict[str, Any] | None = None
    ):
        body = b"" if content is None else dumps(content)
        super().__init__(body, status_code, headers, self.media_type)
        if content is None:
            # Assignment replaces any value Starlette set; MutableHeaders has no pop().
            self.headers["content-length"] = "0"


def write_json(data: Any, status: int = 200) -> Response:
    return JSONResp(data, status)


def no_content() -> Response:
    return Response(status_code=204)


def error_response(err: AppError) -> Response:
    return JSONResp(err.envelope(), err.status)


# --------------------------------------------------------------------------
# Request helpers
# --------------------------------------------------------------------------


async def read_json(request: Request) -> dict[str, Any]:
    """The decoded JSON object body; 400 "invalid body" when it is not one."""
    try:
        body = await request.json()
    except ValueError:
        raise bad_request("invalid body") from None
    if not isinstance(body, dict):
        raise bad_request("invalid body")
    return body


def _coerce(value: Any, tp: Any) -> Any:
    """Decode one JSON value into a typed field: null leaves
    the zero value, a wrong JSON type is an error. `tp` is str/float/int/bool/list[str]/
    dict/Any, optionally `| None` (then null and absent stay None)."""
    args = getattr(tp, "__args__", ())
    optional = type(None) in args
    base: Any = next((a for a in args if a is not type(None)), tp) if optional else tp
    if value is None:
        if optional:
            return None
        is_list = base is list or getattr(base, "__origin__", None) is list
        zero: dict[object, object] = {str: "", float: 0.0, int: 0, bool: False}
        return zero.get(base, [] if is_list else None)
    if base is Any:
        return value
    if base is str and isinstance(value, str):
        return value
    if base is bool and isinstance(value, bool):
        return value
    if base is int and isinstance(value, int) and not isinstance(value, bool):
        return value
    if base is float and isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if base is dict and isinstance(value, dict):
        return value
    if getattr(base, "__origin__", None) is list and isinstance(value, list):
        (item,) = get_args(base)
        return [_coerce(v, item) for v in value]
    raise ValueError("wrong JSON type")


async def read_body(request: Request, spec: dict[str, Any], message: str = "invalid JSON body"):
    """Decode a JSON object body into the fields of `spec` ({name: type}); a malformed
    body or a field of the wrong JSON type is a 400. Unknown fields are ignored."""
    try:
        raw = await request.json()
        if not isinstance(raw, dict):
            raise ValueError
        return {name: _coerce(raw.get(name), tp) for name, tp in spec.items()}
    except ValueError:
        raise bad_request(message) from None


def body_field(raw: dict[str, Any], name: str, tp: Any, message: str = "invalid body") -> Any:
    """One field of an already-read JSON object, decoded like read_body does."""
    try:
        return _coerce(raw.get(name), tp)
    except ValueError:
        raise bad_request(message) from None


def parse_uuid(value: str, message: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise bad_request(message) from None


def path_uuid(request: Request, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(request.path_params[name])
    except (ValueError, KeyError):
        raise bad_request(f"invalid {name}") from None


def query_uuid(request: Request, name: str) -> uuid.UUID | None:
    """The UUID in the query string; None when absent or malformed."""
    value = request.query_params.get(name, "")
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def query_int(request: Request, name: str, default: int) -> int:
    value = request.query_params.get(name, "")
    try:
        return int(value) if value else default
    except ValueError:
        return default


def parse_date(value: str) -> date:
    """Exactly YYYY-MM-DD."""
    try:
        if len(value) != 10:
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise bad_request("invalid date") from None


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --------------------------------------------------------------------------
# Route wrapper: error mapping + the chi middleware groups as decorators
# --------------------------------------------------------------------------


def _not_a_member() -> AppError:
    return AppError(403, "not_a_member", "actor has no active teaching membership in this tenant")


def handle(pattern: str, fn: Handler) -> Handler:
    """Wrap a handler: remember the route pattern for the request log and render any
    exception as the error envelope. 5xx envelopes are opaque; the cause is logged."""

    async def wrapper(request: Request) -> Response:
        request.scope["mawta_route"] = pattern
        try:
            return await fn(request)
        except Exception as exc:
            err = map_error(exc)
            if err.status >= 500:
                cause = applog.sanitize_error_cause(exc)
                request.scope["mawta_error_cause"] = cause
                applog.error(
                    api_of(request).logger,
                    "httpapi: internal error",
                    error=cause,
                    request_id=request.scope.get("request_id", ""),
                )
            return error_response(err)

    return wrapper


def authenticate(fn: Handler) -> Handler:
    """Validate the session cookie and store the tenant context (no teacher yet).
    Open to every logged-in role."""

    async def wrapper(request: Request) -> Response:
        api = api_of(request)
        req_id = request.scope.get("request_id", "")

        token = request.cookies.get(api.settings.session_cookie_name, "")
        if not token:
            raise AppError(401, "missing_session", "no hay una sesión activa")
        token_hash = authpkg.hash_session_token(token)

        async with api.db.auth_tx(req_id) as conn:
            session = await auth_repo.find_live_session(conn, token_hash)
        if session is None:
            resp = error_response(AppError(401, "invalid_session", "sesión inválida"))
            clear_session_cookie(api, resp)
            return resp

        now = datetime.now(UTC)
        expired = session["expires_at"] < now
        idle = (now - session["last_seen_at"]).total_seconds() > api.settings.session_idle_timeout
        if expired or idle:
            reason = (
                domain.SESSION_REVOKE_IDLE
                if idle and not expired
                else domain.SESSION_REVOKE_EXPIRED
            )
            try:
                async with api.db.auth_tx(req_id) as conn:
                    await auth_repo.revoke_session(conn, session["id"], reason)
            except psycopg.Error as exc:
                applog.error(api.logger, "revoke expired session", error=str(exc))
            resp = error_response(AppError(401, "session_expired", "tu sesión expiró"))
            clear_session_cookie(api, resp)
            return resp

        if session["role"] not in domain.LOGIN_ENABLED_ROLES:
            raise AppError(403, "role_not_enabled", "el acceso para tu rol aún no está disponible")

        # Throttled, and done in the auth tx, not the tenant tx, so a handler
        # rollback can't undo it.
        try:
            async with api.db.auth_tx(req_id) as conn:
                await auth_repo.touch_session(conn, session["id"], 3600.0)
        except psycopg.Error as exc:
            applog.warn(api.logger, "touch session", error=str(exc))

        request.state.tc = TenantCtx(
            tenant_id=session["tenant_id"],
            actor_id=session["user_id"],
            request_id=req_id,
            role=session["role"],
        )
        return await fn(request)

    return wrapper


def require_teacher(fn: Handler) -> Handler:
    """Resolve the teacher profile of an authenticated session. Any other role gets 403."""

    async def wrapper(request: Request) -> Response:
        api = api_of(request)
        tc = tc_of(request)
        if tc.role != domain.ROLE_TEACHER:
            raise _not_a_member()
        async with api.db.tenant_tx(tc) as conn:
            assert tc.actor_id is not None
            teacher_id = await auth_repo.resolve_teacher(conn, tc.actor_id)
        if teacher_id is None:
            raise _not_a_member()
        request.state.tc = tc.with_teacher(teacher_id)
        return await fn(request)

    return wrapper


def require_director(fn: Handler) -> Handler:
    async def wrapper(request: Request) -> Response:
        if tc_of(request).role != domain.ROLE_DIRECTOR:
            raise AppError(403, "not_a_director", "solo la dirección puede usar esta función")
        return await fn(request)

    return wrapper


def session_auth(fn: Handler) -> Handler:
    """authenticate + require_teacher: the whole protected teacher surface."""
    return authenticate(require_teacher(fn))


# --------------------------------------------------------------------------
# Session cookie
# --------------------------------------------------------------------------


def set_session_cookie(api: Api, response: Response, token: str, expires: datetime) -> None:
    max_age = max(int((expires - datetime.now(UTC)).total_seconds()), 0)
    response.set_cookie(
        api.settings.session_cookie_name,
        token,
        max_age=max_age,
        expires=expires,
        path="/",
        httponly=True,
        secure=api.settings.session_cookie_secure,
        samesite="lax",
    )


def clear_session_cookie(api: Api, response: Response) -> None:
    response.delete_cookie(
        api.settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=api.settings.session_cookie_secure,
        samesite="lax",
    )


# --------------------------------------------------------------------------
# ASGI middleware: request id + one completion event per request
# --------------------------------------------------------------------------


class _ResponseState(TypedDict):
    status: int
    started: bool
    content_type: str


class RequestLogMiddleware:
    """Assign/propagate X-Request-ID and emit one `http.request` event per request.

    Pure ASGI (not BaseHTTPMiddleware) so streaming responses stay streaming and the
    status/body are observed as they are sent. Nothing here can fail a response: the
    capture is bounded and the log write happens after the response is sent.
    """

    def __init__(self, app: ASGIApp, logger: logging.Logger, capture: bool) -> None:
        self.app = app
        self.logger = logger
        self.policy = applog.CapturePolicy(enabled=capture)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])
        request_id = headers.get(b"x-request-id", b"").decode() or str(uuid.uuid4())
        scope["request_id"] = request_id
        start = time.monotonic()
        state: _ResponseState = {"status": 200, "started": False, "content_type": ""}
        req_body = bytearray()
        resp_body = bytearray()
        limit = self.policy.max_bytes if self.policy.enabled else 0

        async def wrapped_receive() -> Message:
            message = await receive()
            if limit and message["type"] == "http.request" and len(req_body) <= limit:
                req_body.extend(message.get("body", b"")[: limit + 1 - len(req_body)])
            return message

        async def wrapped_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["started"] = True
                raw = list(message.get("headers", []))
                raw.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": raw}
                for name, value in raw:
                    if name.lower() == b"content-type":
                        state["content_type"] = value.decode()
            elif message["type"] == "http.response.body" and limit and len(resp_body) <= limit:
                resp_body.extend(message.get("body", b"")[: limit + 1 - len(resp_body)])
            await send(message)

        try:
            await self.app(scope, wrapped_receive, wrapped_send)
        except Exception as exc:  # the net for anything the route wrapper did not catch
            cause = applog.sanitize_error_cause(exc)
            scope["mawta_error_cause"] = cause
            applog.error(
                self.logger,
                "httpapi: recovered panic",
                event="http.panic",
                request_id=request_id,
                method=scope["method"],
                route=_route(scope),
                error=cause,
            )
            if not state["started"]:
                state["status"] = 500
                await wrapped_send(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [(b"content-type", b"application/json; charset=utf-8")],
                    }
                )
                body = dumps(AppError(500, "internal_error", "internal error").envelope())
                await wrapped_send({"type": "http.response.body", "body": body})

        route = _route(scope)
        req_ct = headers.get(b"content-type", b"").decode()
        req_cap = self.policy.capture_request_body(route, req_ct, bytes(req_body))
        resp_cap = self.policy.capture_response_body(route, state["content_type"], bytes(resp_body))
        fields: dict[str, Any] = {
            "event": "http.request",
            "request_id": request_id,
            "method": scope["method"],
            "route": route,
            "status": state["status"],
            "duration_ms": int((time.monotonic() - start) * 1000),
            "request": req_cap.value,
            "request_capture": req_cap.status,
            "response": resp_cap.value,
            "response_capture": resp_cap.status,
        }
        if state["status"] >= 500 and scope.get("mawta_error_cause"):
            fields["error"] = scope["mawta_error_cause"]
        applog.info(self.logger, "request", **fields)


def _route(scope: Scope) -> str:
    """The route pattern; the raw path when nothing matched (a 404)."""
    return scope.get("mawta_route") or scope["path"]
