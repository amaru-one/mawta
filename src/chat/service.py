"""The director chat inside the app: its model, its LangGraph graph and checkpointer, and the limit
on questions answered at once.

The chat is available when it has a model (CHAT_MODEL, or one handed in by the tests) and its
memory (LANGGRAPH_DATABASE_URL). Without them the app runs anyway: listing and managing chats
works, asking answers chat_unavailable.
"""

from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from agent.llm.providers import client_for
from chat.graph import build_graph
from chat.llm import LLM, OpenAICompatLLM
from errors import AppError
from settings import Settings

# A model answer can take a while (several tool rounds); this bounds one model call.
MODEL_TIMEOUT = 120.0


def unavailable() -> AppError:
    return AppError(503, "chat_unavailable", "el chat de dirección aún no está disponible")


def busy() -> AppError:
    return AppError(
        429, "chat_busy", "el chat está respondiendo otras preguntas; inténtalo en unos segundos"
    )


@dataclass
class ChatService:
    settings: Settings
    llm: LLM | None = None
    graph: Any = None
    saver: AsyncPostgresSaver | None = None
    # Questions being answered now. The app runs on one event loop and nothing awaits between
    # the check and the increment, so a plain counter is enough.
    answering: int = field(default=0, init=False)

    @property
    def ready(self) -> bool:
        return self.graph is not None

    async def start(self, stack: AsyncExitStack) -> None:
        """Build the model and open the checkpointer, when the chat has what it needs. The
        checkpointer's connection is closed by `stack` on shutdown."""
        cfg = self.settings
        if self.llm is None and cfg.chat_ready():
            ref = cfg.chat_model_ref()
            assert ref is not None
            self.llm = OpenAICompatLLM(
                client_for(ref, cfg.endpoints(), timeout=MODEL_TIMEOUT),
                ref,
                max_tokens=cfg.chat_max_tokens,
                reasoning_effort=cfg.chat_reasoning_effort,
            )
        if self.llm is None or not cfg.langgraph_database_url:
            return
        saver = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(cfg.langgraph_database_url)
        )
        # Creates LangGraph's own tables in schema langgraph the first time.
        await saver.setup()
        self.saver = saver
        self.graph = build_graph(self.llm, cfg.chat_max_model_calls, saver)

    def take_slot(self) -> None:
        """Claim one of the chat_max_concurrent answering slots, or refuse with chat_busy. The
        caller must call release_slot() when the answer ends."""
        if not self.ready:
            raise unavailable()
        if self.answering >= self.settings.chat_max_concurrent:
            raise busy()
        self.answering += 1

    def release_slot(self) -> None:
        self.answering -= 1
