"""Test setup: a real Postgres with mawta-server's own migrations and test
fixture (internal/dbtest/fixture.sql), and a fake model, so no test calls
Claude.

The database tests need MAWTA_TEST_ADMIN_URL (a superuser connection string,
the same variable the Go tests use); without it they are skipped.
"""

import base64
import os
import secrets
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any, LiteralString, cast
from uuid import UUID

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from llm import ModelTurn
from main import create_app
from settings import Settings

SERVER = Path(__file__).resolve().parents[2] / "mawta-api"

# Rows of internal/dbtest/fixture.sql.
TENANT_A = UUID("a0000000-0000-4000-8000-000000000001")  # I.E. Cristo Rey
USER_QUISPE = UUID("a0000000-0000-4000-8000-000000000010")
USER_ROJAS = UUID("a0000000-0000-4000-8000-000000000020")
TENANT_B = UUID("b0000000-0000-4000-8000-000000000001")  # I.E. San Martín
USER_FLORES = UUID("b0000000-0000-4000-8000-000000000010")

KEY_ID = "k-test"

# make_token(user, tenant, role=..., key=..., kid=..., ttl=..., **claim_overrides)
MakeToken = Callable[..., str]


def goose_up(text: str) -> LiteralString:
    # The repository's own migration files, so the text is trusted SQL.
    return cast(LiteralString, text.split("-- +goose Up", 1)[1].split("-- +goose Down", 1)[0])


@pytest.fixture(scope="session")
def databases() -> Iterator[tuple[str, str]]:
    admin = os.environ.get("MAWTA_TEST_ADMIN_URL")
    if not admin:
        pytest.skip("MAWTA_TEST_ADMIN_URL is not set, so there is no database to test against")
    suffix = secrets.token_hex(4)
    mawta_db, langgraph_db = f"chat_test_{suffix}", f"langgraph_test_{suffix}"
    base = conninfo_to_dict(admin)
    with psycopg.connect(admin, autocommit=True) as conn:
        for name in (mawta_db, langgraph_db):
            conn.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    with psycopg.connect(
        make_conninfo("", **{**base, "dbname": mawta_db}), autocommit=True
    ) as conn:
        for migration in sorted((SERVER / "migrations").glob("*.sql")):
            conn.execute(goose_up(migration.read_text()))
        conn.execute(cast(LiteralString, (SERVER / "tests/fixture.sql").read_text()))
        conn.execute("alter role mawta_chat password 'chat-test'")
    yield (
        make_conninfo(
            "", **{**base, "dbname": mawta_db, "user": "mawta_chat", "password": "chat-test"}
        ),
        make_conninfo("", **{**base, "dbname": langgraph_db}),
    )
    with psycopg.connect(admin, autocommit=True) as conn:
        for name in (mawta_db, langgraph_db):
            conn.execute(
                sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name))
            )


@pytest.fixture(scope="session")
def signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture(scope="session")
def public_keys(signing_key: Ed25519PrivateKey) -> dict[str, str]:
    raw = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {KEY_ID: base64.b64encode(raw).decode()}


@pytest.fixture(scope="session")
def make_token(signing_key: Ed25519PrivateKey) -> MakeToken:
    """A chat token the way mawta-server signs it (internal/chattoken)."""

    def make(
        user: UUID,
        tenant: UUID,
        role: str = "director",
        key: Ed25519PrivateKey | None = None,
        kid: str = KEY_ID,
        ttl: int = 3600,
        **overrides: Any,
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": "mawta-server",
            "aud": "mawta-chat",
            "sub": str(user),
            "tenant_id": str(tenant),
            "role": role,
            "iat": now,
            "exp": now + ttl,
            "jti": secrets.token_hex(8),
            **overrides,
        }
        return jwt.encode(claims, key or signing_key, algorithm="EdDSA", headers={"kid": kid})

    return make


class FakeLLM:
    """Plays back scripted turns and records what it was sent."""

    model: str = "fake-model"

    def __init__(self) -> None:
        self.turns: list[ModelTurn | Exception] = []
        self.calls: list[list[dict[str, Any]]] = []

    def script(self, *turns: ModelTurn | Exception) -> None:
        self.turns.extend(turns)

    async def respond(
        self,
        _system: str,
        messages: list[dict[str, Any]],
        _tools: list[dict[str, Any]],
        on_text: Callable[[str], None],
        /,
    ) -> ModelTurn:
        self.calls.append([dict(m) for m in messages])
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        for block in turn.content:
            if block.get("type") == "text":
                for start in range(0, len(block["text"]), 7):
                    on_text(block["text"][start : start + 7])
        return turn


def tool_turn(tool_id: str = "toolu_1") -> ModelTurn:
    return ModelTurn(
        content=[{"type": "tool_use", "id": tool_id, "name": "secciones_del_colegio", "input": {}}],
        stop_reason="tool_use",
        model="fake-model",
        input_tokens=100,
        output_tokens=10,
    )


def text_turn(text: str) -> ModelTurn:
    return ModelTurn(
        content=[{"type": "text", "text": text}],
        stop_reason="end_turn",
        model="fake-model",
        input_tokens=150,
        output_tokens=20,
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
async def client(
    databases: tuple[str, str], public_keys: dict[str, str], fake_llm: FakeLLM
) -> AsyncIterator[httpx.AsyncClient]:
    chat_url, langgraph_url = databases
    # _env_file is a pydantic-settings init option missing from the typed signature.
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        chat_database_url=chat_url,
        langgraph_database_url=langgraph_url,
        chat_token_public_keys=public_keys,
        anthropic_api_key="unused-in-tests",
    )
    app = create_app(settings, fake_llm)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
