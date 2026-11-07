"""Test setup: a real Postgres migrated by Alembic and loaded with the test school
(tests/fixtures.py), exercised through the real ASGI app.

The database tests need MAWTA_TEST_ADMIN_URL (a superuser connection string, the same variable CI
sets); without it they are skipped. One database is created per test session (one for the API
tests, another for tests/chat, which loads more data), migrated as the superuser, loaded, and
dropped at the end. The app connects as the superuser with `-c role=mawta_app`, so it runs as
the application's role, a missing GRANT shows up here, and it can still SET ROLE mawta_chat.
"""

import os
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AsyncExitStack, contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, final

import httpx
import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.rows import DictRow, dict_row
from sqlalchemy import Connection, create_engine, delete, func, insert, select
from sqlalchemy.engine import make_url
from starlette.applications import Starlette

import auth as authpkg
from chat.llm import LLM
from db import sa_url
from main import create_app
from mawta_schema.tables import Membership, UserSession
from settings import Settings
from tests import fixtures

ROOT = Path(__file__).resolve().parents[1]
COOKIE_NAME = "mawta_session"


def _id(suffix: str) -> uuid.UUID:
    return uuid.UUID(f"a0000000-0000-4000-8000-{suffix:0>12}")


@final
@dataclass(frozen=True)
class Fixture:
    """The rows tests/fixtures.py creates, with fixed ids.

    In Cristo Rey, Quispe teaches Matemática to 5to B and Rojas teaches nothing (the same-school
    teacher who must not reach Quispe's class). Bimestre II is the live term; Bimestre I is
    closed behind it. Ana and Beto are the school's two directors.
    """

    school = _id("1")
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
    # The two directors, Ana and Beto: a user and a director membership each, no teacher row.
    user_ana = uuid.UUID("a0000000-0000-4000-8000-0000000000d0")
    membership_ana = uuid.UUID("a0000000-0000-4000-8000-0000000000d1")
    user_beto = uuid.UUID("a0000000-0000-4000-8000-0000000000e0")
    membership_beto = uuid.UUID("a0000000-0000-4000-8000-0000000000e1")


FX = Fixture()

Loader = Callable[[Connection], None]


@dataclass
class Databases:
    name: str
    admin_url: str  # superuser, on the test database
    app_url: str  # superuser that runs as mawta_app (options -c role=mawta_app)
    langgraph_url: str  # superuser, search_path langgraph: LangGraph's checkpoints


def _with_options(url: str, options: str) -> str:
    return f"{url}?options={options.replace(' ', '%20').replace('=', '%3D')}"


@contextmanager
def migrated_database(loaders: list[Loader]) -> Iterator[Databases]:
    """A new database migrated to head and loaded by `loaders`, dropped on exit (unless
    MAWTA_TEST_KEEP is set). Skips the test when there is no MAWTA_TEST_ADMIN_URL."""
    admin = os.environ.get("MAWTA_TEST_ADMIN_URL")
    if not admin:
        pytest.skip("MAWTA_TEST_ADMIN_URL is not set, so there is no database to test against")
    name = f"mawta_test_{secrets.token_hex(6)}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    admin_url = make_url(admin).set(database=name).render_as_string(hide_password=False)

    engine = create_engine(sa_url(admin_url))
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["skip_logging"] = True
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        for load in loaders:
            load(conn)
    engine.dispose()
    try:
        yield Databases(
            name=name,
            admin_url=admin_url,
            app_url=_with_options(admin_url, "-c role=mawta_app"),
            langgraph_url=_with_options(admin_url, "-c search_path=langgraph"),
        )
    finally:
        if not os.environ.get("MAWTA_TEST_KEEP"):
            with psycopg.connect(admin, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name))
                )


@pytest.fixture(scope="session")
def databases() -> Iterator[Databases]:
    """The API tests' database: the test school. tests/chat overrides it with one that also has
    the chat's levels."""
    with migrated_database([fixtures.load]) as dbs:
        yield dbs


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
        # The chat has a model only when a test hands one in (chat_llm); the setting just
        # names it.
        "chat_model": "local:fake",
        "langgraph_database_url": databases.langgraph_url,
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
# make_client(chat_llm=None, **settings_overrides) -> a Client on a fresh app
MakeClient = Callable[..., Awaitable[Client]]
# login(user_id, role="teacher") -> a session cookie value
Login = Callable[..., Awaitable[str]]


@pytest_asyncio.fixture
async def make_client(databases: Databases, tmp_path: Path) -> AsyncIterator[MakeClient]:
    async with AsyncExitStack() as stack:

        async def build(chat_llm: LLM | None = None, **overrides: Any) -> Client:
            app = create_app(make_settings(databases, tmp_path, **overrides), chat_llm=chat_llm)
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
    """A superuser connection (autocommit) for setup and assertions behind the app's back."""
    conn = await psycopg.AsyncConnection[DictRow].connect(
        databases.admin_url, autocommit=True, row_factory=dict_row
    )
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def login(databases: Databases) -> AsyncIterator[Login]:
    """Mint a real session row for a user and return its cookie value."""
    engine = create_engine(sa_url(databases.admin_url))
    hashes: list[bytes] = []

    async def mint(user_id: uuid.UUID, role: str = "teacher") -> str:
        token, token_hash = authpkg.new_session_token()
        with engine.begin() as conn:
            membership = conn.execute(
                select(Membership.id).where(
                    Membership.user_id == user_id, Membership.deleted_at.is_(None)
                )
            ).scalar_one_or_none()
            assert membership is not None, "no membership for that user"
            conn.execute(
                insert(UserSession).values(
                    token_hash=token_hash,
                    user_id=user_id,
                    membership_id=membership,
                    role=role,
                    expires_at=func.now() + timedelta(hours=1),
                )
            )
        hashes.append(token_hash)
        return token

    yield mint
    with engine.begin() as conn:
        for token_hash in hashes:
            conn.execute(delete(UserSession).where(UserSession.token_hash == token_hash))
    engine.dispose()


def returned(row: DictRow | None) -> DictRow:
    """The row of an admin statement that always yields one (insert ... returning)."""
    assert row is not None, "the statement returned no row"
    return row


def error_code(response: httpx.Response) -> str:
    try:
        return response.json().get("error", {}).get("code", "")
    except ValueError:
        return ""
