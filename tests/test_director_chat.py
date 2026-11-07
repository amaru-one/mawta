"""The director role: a login without a teacher profile, and no chat token any more (the chat
uses the same session; see tests/chat)."""

import uuid

import auth as authpkg
from tests.conftest import COOKIE_NAME, Client, error_code
from tests.test_auth import post_login

DIRECTOR, PASSWORD = "adirectora", "ana-clave-2026"


async def director_session(client: Client) -> str:
    resp = await post_login(client, DIRECTOR, PASSWORD)
    assert resp.status_code == 200, resp.text
    return resp.cookies[COOKIE_NAME]


async def test_director_logs_in_without_a_teacher_profile(client: Client):
    resp = await post_login(client, DIRECTOR, PASSWORD)
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "director"
    assert resp.json()["teacher"]["id"] == str(uuid.UUID(int=0))
    token = resp.cookies[COOKIE_NAME]

    assert (await client.do(token, "GET", "/api/v1/me")).status_code == 200
    home = await client.do(token, "GET", "/api/v1/home")
    assert home.status_code == 403
    assert error_code(home) == "not_a_member"


async def test_a_director_has_me_without_a_teacher(client: Client):
    me = (await client.do(await director_session(client), "GET", "/api/v1/me")).json()
    assert me["role"] == "director"
    assert me["school"] == {"name": "I.E. Cristo Rey", "city": None, "timezone": "America/Lima"}
    assert "tenant" not in me


async def test_the_chat_token_route_is_gone(client: Client):
    resp = await client.do(await director_session(client), "GET", "/api/v1/auth/chat-token")
    assert resp.status_code == 404


def test_session_token_shape():
    token, token_hash = authpkg.new_session_token()
    assert len(token) == 43 and len(token_hash) == 32
    assert authpkg.hash_session_token(token) == token_hash
