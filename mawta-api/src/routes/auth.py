"""Login, logout, /me, the director's chat token and /healthz."""

from datetime import UTC, datetime, timedelta

import psycopg
from starlette.requests import Request
from starlette.responses import Response

import applog
import auth as authpkg
import domain
from db import TenantCtx
from errors import AppError, bad_request
from repo import auth as auth_repo
from repo import events as events_repo
from repo import me as me_repo
from web import (
    api_of,
    clear_session_cookie,
    client_ip,
    no_content,
    read_json,
    set_session_cookie,
    tc_of,
    write_json,
)

_INVALID_CREDENTIALS = ("invalid_credentials", "usuario o contraseña incorrectos")


def _invalid_credentials() -> AppError:
    return AppError(401, *_INVALID_CREDENTIALS)


async def handle_login(request: Request) -> Response:
    """Resolve a username+password to a session, set the cookie and return the /me payload."""
    api = api_of(request)
    cfg = api.settings
    body = await read_json(request)
    raw_username, raw_password = body.get("username"), body.get("password")
    if not isinstance(raw_username, str | None) or not isinstance(raw_password, str | None):
        raise bad_request("invalid body")
    username = (raw_username or "").strip().lower()
    password = raw_password or ""
    if not username or not password:
        raise _invalid_credentials()

    req_id = request.scope.get("request_id", "")

    async with api.db.auth_tx(req_id) as conn:
        candidate = await auth_repo.find_login_candidate(conn, username)

    if candidate is None:
        # Always verify against a real bcrypt hash so a missing username takes the
        # same time as a wrong password on a real one.
        _verify(authpkg.dummy_hash(), password)
        applog.info(
            api.logger, "login failed", reason="no_such_user", username=username, request_id=req_id
        )
        raise _invalid_credentials()

    locked_until = candidate["locked_until"]
    if locked_until is not None and locked_until > datetime.now(UTC):
        raise AppError(429, "account_locked", "demasiados intentos; espera unos minutos")

    if candidate["status"] != "active":
        # Not a distinct code: an invited/suspended/deactivated account must be
        # indistinguishable from a wrong password.
        applog.info(
            api.logger,
            "login failed",
            reason="inactive_status",
            user_id=candidate["user_id"],
            status=candidate["status"],
            request_id=req_id,
        )
        raise _invalid_credentials()

    if not _verify(candidate["password_hash"], password):
        try:
            async with api.db.auth_tx(req_id) as conn:
                await auth_repo.record_login_failure(
                    conn, candidate["user_id"], cfg.login_max_failures, cfg.login_lockout
                )
        except psycopg.Error as exc:
            applog.error(api.logger, "record login failure", error=str(exc))
        applog.info(
            api.logger,
            "login failed",
            reason="bad_password",
            user_id=candidate["user_id"],
            request_id=req_id,
        )
        raise _invalid_credentials()

    async with api.db.auth_tx(req_id) as conn:
        membership = await auth_repo.resolve_membership(conn, candidate["user_id"])
    if membership is None:
        raise AppError(403, "no_membership", "tu cuenta no está activa en ningún colegio")

    if membership["role"] not in domain.LOGIN_ENABLED_ROLES:
        # Checked after the password, deliberately: this must not be usable as a
        # username/role enumeration oracle.
        raise AppError(403, "role_not_enabled", "el acceso para tu rol aún no está disponible")

    user_id = candidate["user_id"]
    tc = TenantCtx(
        tenant_id=membership["tenant_id"],
        actor_id=user_id,
        request_id=req_id,
        role=membership["role"],
    )
    async with api.db.tenant_tx(tc) as conn:
        if membership["role"] == domain.ROLE_DIRECTOR:
            me = await me_repo.get_director_me(conn, user_id)
        else:
            teacher_id = await auth_repo.resolve_teacher(conn, user_id)
            if teacher_id is None:
                raise AppError(
                    403,
                    "not_a_teacher_profile",
                    "tu cuenta no tiene un perfil docente en este colegio",
                )
            me = await me_repo.get_me(conn, teacher_id)
        await events_repo.log_event(conn, "auth.login", "user", user_id)

    token, token_hash = authpkg.new_session_token()
    expires_at = datetime.now(UTC) + timedelta(seconds=cfg.session_ttl)

    async with api.db.auth_tx(req_id) as conn:
        await auth_repo.create_session(
            conn,
            token_hash=token_hash,
            user_id=user_id,
            tenant_id=membership["tenant_id"],
            membership_id=membership["membership_id"],
            role=membership["role"],
            expires_at=expires_at,
            user_agent=request.headers.get("user-agent", ""),
            ip=client_ip(request),
        )
        await auth_repo.record_login_success(conn, user_id)
        try:
            async with conn.transaction():  # savepoint: a failed prune must not undo the login
                await auth_repo.prune_sessions(conn, 30 * 24 * 3600.0)
        except psycopg.Error as exc:
            applog.warn(api.logger, "prune sessions", error=str(exc))

    me["role"] = membership["role"]
    response = write_json(me)
    set_session_cookie(api, response, token, expires_at)
    return response


def _verify(hashed: str, password: str) -> bool:
    try:
        authpkg.verify_password(hashed, password)
    except authpkg.PasswordMismatch:
        return False
    return True


async def handle_logout(request: Request) -> Response:
    """Revoke the session if a cookie is present and always clear the cookie. Idempotent."""
    api = api_of(request)
    token = request.cookies.get(api.settings.session_cookie_name, "")
    if token:
        try:
            async with api.db.auth_tx(request.scope.get("request_id", "")) as conn:
                await auth_repo.revoke_session_by_token_hash(
                    conn, authpkg.hash_session_token(token), domain.SESSION_REVOKE_LOGOUT
                )
        except psycopg.Error as exc:
            applog.error(api.logger, "revoke session", error=str(exc))
    response = no_content()
    clear_session_cookie(api, response)
    return response


async def handle_me(request: Request) -> Response:
    """Answers for every logged-in role; a director has no teacher profile."""
    api = api_of(request)
    tc = tc_of(request)
    assert tc.actor_id is not None
    async with api.db.tenant_tx(tc) as conn:
        if tc.role == domain.ROLE_DIRECTOR:
            me = await me_repo.get_director_me(conn, tc.actor_id)
        else:
            teacher_id = await auth_repo.resolve_teacher(conn, tc.actor_id)
            if teacher_id is None:
                raise AppError(
                    403,
                    "not_a_member",
                    "actor has no active teaching membership in this tenant",
                )
            me = await me_repo.get_me(conn, teacher_id)
    me["role"] = tc.role
    return write_json(me)


async def handle_chat_token(request: Request) -> Response:
    """The token the director's browser sends to the chat service."""
    api = api_of(request)
    if api.chat_tokens is None:
        raise AppError(503, "chat_unavailable", "el chat de dirección aún no está disponible")
    tc = tc_of(request)
    assert tc.actor_id is not None
    token, expires_at = api.chat_tokens.issue(tc.actor_id, tc.tenant_id, tc.role)
    response = write_json({"token": token, "expires_at": expires_at})
    response.headers["Cache-Control"] = "no-store"
    return response


async def handle_healthz(request: Request) -> Response:
    try:
        await api_of(request).db.ping()
    except Exception:
        return write_json({"ok": False}, 503)
    return write_json({"ok": True})
