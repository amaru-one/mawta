"""Test setup: a real Postgres with this service's own migrations and the test
fixture (tests/fixture.sql), exercised through the real ASGI app.

The database tests need MAWTA_TEST_ADMIN_URL (a superuser connection string, the
same variable CI sets); without it they are skipped. One database is created per
test session, migrated as the superuser, seeded, and dropped at the end. The app
connects as mawta_app (`-c role=mawta_app`), so a missing GRANT shows up here.
"""

import os
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, LiteralString, cast, final

import httpx
import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import DictRow, dict_row
from starlette.applications import Starlette

import auth as authpkg
from main import create_app
from settings import Settings

ROOT = Path(__file__).resolve().parents[1]
COOKIE_NAME = "mawta_session"


def _id(suffix: str, tenant: str = "a") -> uuid.UUID:
    return uuid.UUID(f"{tenant}0000000-0000-4000-8000-{suffix:0>12}")


@final
@dataclass(frozen=True)
class Fixture:
    """The rows tests/fixture.sql creates, with fixed ids.

    Two schools. In Cristo Rey, Quispe teaches Matemática to 5to B and Rojas
    teaches nothing (the same-school teacher who must not reach Quispe's class).
    San Martín is a second school, to prove tenant isolation. Bimestre II is the
    live term; Bimestre I is closed behind it.
    """

    tenant_a = _id("1")
    user_quispe = _id("10")
    teacher_quispe = _id("11")
    user_rojas = _id("20")
    teacher_rojas = _id("21")
    year_a = _id("30")
    term_i = _id("31")
    term_ii = _id("32")
    grade_level = _id("40")
    section_b = _id("41")
    subject_mat = _id("50")
    course_mat = _id("51")
    class_mat_5b = _id("52")
    competency_c1 = _id("60")
    competency_c2 = _id("61")
    capability_c2 = _id("62")
    criterion_one = _id("63")
    criterion_two = _id("64")
    scale_minedu = _id("70")
    level_ad = _id("71")
    level_a = _id("72")
    level_b = _id("73")
    level_c = _id("74")
    students = tuple(_id(str(n)) for n in range(101, 106))
    session_one = _id("110")
    assessment_numeric = _id("120")
    assessment_ordinal = _id("121")
    score_one = _id("122")
    tenant_b = _id("1", "b")
    user_flores = _id("10", "b")
    teacher_flores = _id("11", "b")
    year_b = _id("30", "b")
    term_b = _id("32", "b")
    class_b = _id("52", "b")
    student_b = _id("101", "b")


FX = Fixture()


def goose_up(text: str) -> LiteralString:
    # The repository's own migration files, so the text is trusted SQL.
    return cast(LiteralString, text.split("-- +goose Up", 1)[1].split("-- +goose Down", 1)[0])


@dataclass
class Databases:
    admin_url: str  # superuser, on the test database
    app_url: str  # connects as mawta_app


@pytest.fixture(scope="session")
def databases() -> Iterator[Databases]:
    admin = os.environ.get("MAWTA_TEST_ADMIN_URL")
    if not admin:
        pytest.skip("MAWTA_TEST_ADMIN_URL is not set, so there is no database to test against")
    name = f"mawta_test_{secrets.token_hex(6)}"
    base = conninfo_to_dict(admin)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    admin_url = make_conninfo("", **{**base, "dbname": name})
    with psycopg.connect(admin_url, autocommit=True) as conn:
        for migration in sorted((ROOT / "migrations").glob("*.sql")):
            conn.execute(goose_up(migration.read_text()))
        conn.execute(cast(LiteralString, (ROOT / "tests" / "fixture.sql").read_text()))
    app_url = make_conninfo("", **{**base, "dbname": name, "options": "-c role=mawta_app"})
    yield Databases(admin_url=admin_url, app_url=app_url)
    if not os.environ.get("MAWTA_TEST_KEEP"):
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name))
            )


def make_settings(databases: Databases, tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": databases.app_url,
        "admin_database_url": databases.admin_url,
        "session_cookie_name": COOKIE_NAME,
        "session_cookie_secure": False,
        # Real durations, not zero: a zero idle timeout revokes every session on its
        # first request.
        "session_ttl": 3600.0,
        "session_idle_timeout": 3600.0,
        "login_max_failures": 8,
        "login_lockout": 900.0,
        "bcrypt_cost": 4,  # the minimum; the default 12 is deliberately slow
        "storage_dir": str(tmp_path),
        "worker_enabled": False,
    }
    values.update(overrides)
    # _env_file is a pydantic-settings init option missing from the typed signature.
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


class Client:
    """httpx against the ASGI app, with the session cookie passed per call."""

    http: httpx.AsyncClient
    app: Starlette

    def __init__(self, http: httpx.AsyncClient, app: Starlette) -> None:
        self.http = http
        self.app = app

    async def do(
        self, token: str, method: str, path: str, body: Any = None, **kwargs: Any
    ) -> httpx.Response:
        headers = {"Cookie": f"{COOKIE_NAME}={token}"} if token else {}
        if body is not None:
            kwargs["json"] = body
        return await self.http.request(method, path, headers=headers, **kwargs)


Admin = psycopg.AsyncConnection[DictRow]
# make_client(**settings_overrides) -> a Client on a fresh app
MakeClient = Callable[..., Awaitable[Client]]
# login(user_id, tenant_id, role="teacher") -> a session cookie value
Login = Callable[..., Awaitable[str]]


@pytest_asyncio.fixture
async def make_client(databases: Databases, tmp_path: Path) -> AsyncIterator[MakeClient]:
    async with AsyncExitStack() as stack:

        async def build(**overrides: Any) -> Client:
            app = create_app(make_settings(databases, tmp_path, **overrides))
            await stack.enter_async_context(app.router.lifespan_context(app))
            http = await stack.enter_async_context(
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
            )
            return Client(http, app)

        yield build


@pytest_asyncio.fixture
async def client(make_client: MakeClient) -> Client:
    return await make_client()


@pytest_asyncio.fixture
async def admin(databases: Databases) -> AsyncIterator[Admin]:
    """A superuser connection (autocommit) for fixture work that bypasses RLS."""
    conn = await psycopg.AsyncConnection[DictRow].connect(
        databases.admin_url, autocommit=True, row_factory=dict_row
    )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def login(admin: Admin) -> AsyncIterator[Login]:
    """Mint a real session row for a user and return its cookie value."""
    hashes: list[bytes] = []

    async def mint(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str = "teacher") -> str:
        token, token_hash = authpkg.new_session_token()
        cur = await admin.execute(
            "select id from memberships where user_id = %s and tenant_id = %s"
            " and deleted_at is null",
            (user_id, tenant_id),
        )
        membership = await cur.fetchone()
        assert membership is not None, "no membership for that user"
        await admin.execute(
            "insert into user_sessions (token_hash, user_id, tenant_id, membership_id, role,"
            " expires_at) values (%s, %s, %s, %s, %s, now() + interval '1 hour')",
            (token_hash, user_id, tenant_id, membership["id"], role),
        )
        hashes.append(token_hash)
        return token

    yield mint
    for token_hash in hashes:
        await admin.execute("delete from user_sessions where token_hash = %s", (token_hash,))


def error_code(response: httpx.Response) -> str:
    try:
        return response.json().get("error", {}).get("code", "")
    except ValueError:
        return ""
