"""Setup for the director chat's tests: the test school plus the chat's levels
(tests/fixtures_levels.py) in their own database, a scripted model instead of a real one, and an
HTTP client rooted at /api/v1/chat.

Ana and Beto are the school's two directors; Quispe is a teacher. Sessions are the same cookie as
the rest of the app: there is no chat token.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any
from uuid import UUID

import httpx
import pytest
import pytest_asyncio

from chat.llm import ModelTurn
from main import create_app
from tests import fixtures, fixtures_levels
from tests.conftest import COOKIE_NAME, FX, Databases, Login, make_settings, migrated_database

ANA = FX.user_ana
BETO = FX.user_beto
QUISPE = FX.user_quispe
SCHOOL = FX.school

# session(user_id, role="director") -> the Cookie header of a live session
Session = Callable[..., Awaitable[dict[str, str]]]


@pytest.fixture(scope="session")
def databases() -> Iterator[Databases]:
    """The chat's own database: the test school plus its levels. Overrides the API tests' one
    (a session fixture is computed once, so overriding only its loaders would not do)."""
    with migrated_database([fixtures.load, fixtures_levels.load]) as dbs:
        yield dbs


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
        text = turn.message.get("content") or ""
        for start in range(0, len(text), 7):
            on_text(text[start : start + 7])
        return turn


def tool_turn(
    tool_id: str = "call_1", arguments: str = "{}", name: str = "datos_del_colegio"
) -> ModelTurn:
    return ModelTurn(
        message={
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tool_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        },
        stop_reason="tool_calls",
        model="fake-model",
        input_tokens=100,
        output_tokens=10,
    )


def text_turn(text: str) -> ModelTurn:
    return ModelTurn(
        message={"role": "assistant", "content": text},
        stop_reason="stop",
        model="fake-model",
        input_tokens=150,
        output_tokens=20,
    )


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest_asyncio.fixture
async def chat_client_for(
    databases: Databases, tmp_path: Any
) -> AsyncIterator[Callable[..., Awaitable[httpx.AsyncClient]]]:
    """chat_client_for(chat_llm, **settings) -> an httpx client at /api/v1/chat on a fresh app."""
    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:

        async def build(chat_llm: Any = None, **overrides: Any) -> httpx.AsyncClient:
            app = create_app(make_settings(databases, tmp_path, **overrides), chat_llm=chat_llm)
            await stack.enter_async_context(app.router.lifespan_context(app))
            return await stack.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1/chat"
                )
            )

        yield build


@pytest_asyncio.fixture
async def client(
    chat_client_for: Callable[..., Awaitable[httpx.AsyncClient]], fake_llm: FakeLLM
) -> httpx.AsyncClient:
    return await chat_client_for(fake_llm)


@pytest_asyncio.fixture
async def session(login: Login) -> Session:
    async def make(user_id: UUID, role: str = "director") -> dict[str, str]:
        return {"Cookie": f"{COOKIE_NAME}={await login(user_id, role)}"}

    return make
