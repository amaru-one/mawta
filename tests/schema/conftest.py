"""A throwaway database per test, migrated by the tests themselves through pytest-alembic.

Needs MAWTA_TEST_ADMIN_URL (a superuser connection string, the same variable the api and chat
tests use); without it every test here is skipped.
"""

import os
import re
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def sa_url(url: str) -> str:
    return re.sub(r"^postgres(ql)?://", "postgresql+psycopg://", url)


@pytest.fixture(scope="session")
def admin_url() -> str:
    url = os.environ.get("MAWTA_TEST_ADMIN_URL")
    if not url:
        pytest.skip("MAWTA_TEST_ADMIN_URL is not set, so there is no database to test against")
    return sa_url(url)


@pytest.fixture
def alembic_config() -> dict[str, str]:
    return {"file": str(ROOT / "alembic.ini")}


@pytest.fixture
def alembic_engine(admin_url: str) -> Iterator[Engine]:
    name = f"schema_test_{secrets.token_hex(4)}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'create database "{name}"'))
    engine = create_engine(make_url(admin_url).set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'drop database if exists "{name}" with (force)'))
        admin.dispose()
