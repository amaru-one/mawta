"""The director role and the chat token."""

import uuid
from datetime import UTC, datetime

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import auth as authpkg
import chattoken
from db import returned
from tests.conftest import COOKIE_NAME, FX, Admin, Client, Login, MakeClient, error_code
from tests.test_auth import TEST_PASSWORD, post_login, set_password

DIRECTOR = "rhuaman-directora"
CHAT_TOKEN = "/api/v1/auth/chat-token"


@pytest_asyncio.fixture
async def director_id(admin: Admin):
    cur = await admin.execute(
        "insert into users (email, given_name, family_name, display_name, username,"
        " password_hash, password_changed_at) values ('directora@example.com', 'Rosa', 'Huamán',"
        " 'Rosa Huamán', %s, 'x', now()) returning id",
        (DIRECTOR,),
    )
    user_id = returned(await cur.fetchone())["id"]
    await admin.execute(
        "insert into memberships (tenant_id, user_id, role, status, joined_at)"
        " values (%s, %s, 'director', 'active', now())",
        (FX.tenant_a, user_id),
    )
    await set_password(admin, DIRECTOR)
    yield user_id
    for sql in (
        "delete from user_sessions where user_id = %s",
        "delete from memberships where user_id = %s",
        "delete from users where id = %s",
    ):
        await admin.execute(sql, (user_id,))


async def director_session(client: Client) -> str:
    resp = await post_login(client, DIRECTOR, TEST_PASSWORD)
    assert resp.status_code == 200, resp.text
    return resp.cookies[COOKIE_NAME]


async def test_director_logs_in_without_a_teacher_profile(client: Client, director_id: uuid.UUID):
    resp = await post_login(client, DIRECTOR, TEST_PASSWORD)
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "director"
    assert resp.json()["teacher"]["id"] == str(uuid.UUID(int=0))
    token = resp.cookies[COOKIE_NAME]

    assert (await client.do(token, "GET", "/api/v1/me")).status_code == 200
    home = await client.do(token, "GET", "/api/v1/home")
    assert home.status_code == 403
    assert error_code(home) == "not_a_member"


@pytest.fixture
def chat_key():
    seed, public = chattoken.generate_key()
    return seed, public


async def test_chat_token_for_a_director(
    make_client: MakeClient, director_id: uuid.UUID, chat_key: tuple[str, str]
):
    seed, public = chat_key
    client = await make_client(
        chat_token_signing_key=seed, chat_token_key_id="k-test", chat_token_ttl=3600.0
    )
    resp = await client.do(await director_session(client), "GET", CHAT_TOKEN)
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    left = (expires - datetime.now(UTC)).total_seconds()
    assert 59 * 60 <= left <= 3600

    import base64

    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public))
    header = jwt.get_unverified_header(body["token"])
    assert header["alg"] == "EdDSA" and header["kid"] == "k-test"
    claims = jwt.decode(
        body["token"], key, algorithms=["EdDSA"], audience="mawta-chat", issuer="mawta-server"
    )
    assert claims["sub"] == str(director_id)
    assert claims["tenant_id"] == str(FX.tenant_a)
    assert claims["role"] == "director"
    uuid.UUID(claims["jti"])


async def test_chat_token_is_only_for_directors(
    make_client: MakeClient, login: Login, chat_key: tuple[str, str]
):
    seed, _ = chat_key
    client = await make_client(chat_token_signing_key=seed, chat_token_key_id="k-test")
    teacher = await login(FX.user_quispe, FX.tenant_a)
    resp = await client.do(teacher, "GET", CHAT_TOKEN)
    assert resp.status_code == 403
    assert error_code(resp) == "not_a_director"
    assert (await client.http.get(CHAT_TOKEN)).status_code == 401


async def test_chat_token_without_a_signing_key(client: Client, director_id: uuid.UUID):
    resp = await client.do(await director_session(client), "GET", CHAT_TOKEN)
    assert resp.status_code == 503
    assert error_code(resp) == "chat_unavailable"


def test_session_token_shape():
    token, token_hash = authpkg.new_session_token()
    assert len(token) == 43 and len(token_hash) == 32
    assert authpkg.hash_session_token(token) == token_hash
