"""Login and session resolution: the one path that runs before a tenant is known,
and therefore the one place where getting the ordering wrong leaks across schools.

The fixture's password hashes are placeholders, so these tests set a real bcrypt
hash on the user first (cost 4, the minimum).
"""

import psycopg
import pytest

import auth as authpkg
from tests.conftest import COOKIE_NAME, FX, error_code

TEST_PASSWORD = "una contraseña larga"


async def set_password(admin: psycopg.AsyncConnection, username: str) -> None:
    hashed = authpkg.hash_password(TEST_PASSWORD, 4)
    await admin.execute(
        "update users set password_hash = %s, failed_login_count = 0, locked_until = null"
        " where username = %s",
        (hashed, username),
    )


async def post_login(client, username: str, password: str):
    return await client.http.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


async def test_login_issues_a_working_session(client, admin):
    await set_password(admin, "jquispe")
    resp = await post_login(client, "jquispe", TEST_PASSWORD)
    assert resp.status_code == 200, resp.text
    cookie = resp.cookies.get(COOKIE_NAME)
    assert cookie
    assert "httponly" in resp.headers["set-cookie"].lower()
    body = resp.json()
    assert body["role"] == "teacher"
    assert list(body) == ["role", "user", "teacher", "tenant"]

    me = await client.do(cookie, "GET", "/api/v1/me")
    assert me.status_code == 200
    await admin.execute(
        "delete from user_sessions where token_hash = %s", (authpkg.hash_session_token(cookie),)
    )


async def test_login_does_not_reveal_whether_a_user_exists(client, admin):
    await set_password(admin, "jquispe")
    wrong = await post_login(client, "jquispe", "la contraseña equivocada")
    nobody = await post_login(client, "nadie-en-absoluto", TEST_PASSWORD)
    assert wrong.status_code == nobody.status_code == 401
    assert error_code(wrong) == error_code(nobody) == "invalid_credentials"


async def test_login_rejects_an_inactive_account_as_invalid_credentials(client, admin):
    await set_password(admin, "mrojas")
    await admin.execute("update users set status = 'suspended' where username = 'mrojas'")
    try:
        resp = await post_login(client, "mrojas", TEST_PASSWORD)
    finally:
        await admin.execute("update users set status = 'active' where username = 'mrojas'")
    assert resp.status_code == 401
    assert error_code(resp) == "invalid_credentials"


async def test_failed_logins_count_towards_lockout(client, admin):
    await set_password(admin, "jquispe")
    assert (await post_login(client, "jquispe", "mal")).status_code == 401
    cur = await admin.execute("select failed_login_count from users where username = 'jquispe'")
    assert (await cur.fetchone())["failed_login_count"] == 1
    await admin.execute(
        "update users set failed_login_count = 0, locked_until = null where username = 'jquispe'"
    )


async def test_lockout_after_max_failures(make_client, admin):
    client = await make_client(login_max_failures=2)
    await set_password(admin, "jquispe")
    for _ in range(2):
        assert (await post_login(client, "jquispe", "mal")).status_code == 401
    locked = await post_login(client, "jquispe", TEST_PASSWORD)
    assert locked.status_code == 429
    assert error_code(locked) == "account_locked"
    await admin.execute(
        "update users set failed_login_count = 0, locked_until = null where username = 'jquispe'"
    )


async def test_login_body_must_be_a_json_object(client):
    resp = await client.http.post("/api/v1/auth/login", content=b"not json")
    assert resp.status_code == 400
    assert error_code(resp) == "bad_request"


class TestSessionResolution:
    path = "/api/v1/me"

    async def test_no_cookie(self, client):
        resp = await client.http.get(self.path)
        assert resp.status_code == 401
        assert error_code(resp) == "missing_session"

    async def test_unknown_token(self, client):
        resp = await client.do("not-a-real-token", "GET", self.path)
        assert resp.status_code == 401
        assert error_code(resp) == "invalid_session"

    async def test_expired_session(self, client, admin, login):
        token = await login(FX.user_quispe, FX.tenant_a)
        # created_at moves too: user_sessions_expires_after_created forbids a row that
        # expired before it existed.
        await admin.execute(
            "update user_sessions set created_at = now() - interval '2 hours',"
            " expires_at = now() - interval '1 minute' where token_hash = %s",
            (authpkg.hash_session_token(token),),
        )
        resp = await client.do(token, "GET", self.path)
        assert resp.status_code == 401
        assert error_code(resp) == "session_expired"

    async def test_revoked_session(self, client, admin, login):
        token = await login(FX.user_quispe, FX.tenant_a)
        await admin.execute(
            "update user_sessions set revoked_at = now(), revoked_reason = 'logout'"
            " where token_hash = %s",
            (authpkg.hash_session_token(token),),
        )
        assert (await client.do(token, "GET", self.path)).status_code == 401


async def test_logout_revokes_the_session_server_side(client, admin, login):
    token = await login(FX.user_quispe, FX.tenant_a)
    assert (await client.do(token, "GET", "/api/v1/me")).status_code == 200
    assert (await client.do(token, "POST", "/api/v1/auth/logout")).status_code == 204
    assert (await client.do(token, "GET", "/api/v1/me")).status_code == 401
    cur = await admin.execute(
        "select revoked_reason from user_sessions where token_hash = %s",
        (authpkg.hash_session_token(token),),
    )
    assert (await cur.fetchone())["revoked_reason"] == "logout"


async def test_healthz(client):
    resp = await client.http.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.parametrize("path", ["/api/v1/home", "/api/v1/profile"])
async def test_teacher_routes_need_a_session(client, path):
    resp = await client.http.get(path)
    assert resp.status_code in (401, 404)  # 404 until the domain routes are ported
