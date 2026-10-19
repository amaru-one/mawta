"""The shared base of Mawta's agents.

Mawta runs several narrow agents (planning, descriptive conclusions, a redaction sweep) and none
of them acts on its own: each generation is one bounded model call over data the server chose,
answered by filling a fixed schema, and the server validates that answer and decides what is
stored. What an agent proposes is saved as pending until the teacher accepts or edits it.

This package owns what every agent repeats: the generation lifecycle in agent_generations, the
model call outside any database transaction, retries, a one-time repair of an invalid answer,
deadlines, usage and cost accounting. An agent only supplies what is its own: what context it
reads (prepare), what it asks (the Spec), and how it validates and stores the answer (apply).
"""

from dataclasses import dataclass
from typing import Any, Protocol

from psycopg import AsyncConnection

from agent.llm import Block, Tool

# The job that runs a generation (jobs.kind).
JOB_KIND = "agent.generate"
# Bounds a generation's retries: transient model failures are retried a couple of times with the
# queue's backoff, then the generation fails and the teacher can write by hand.
MAX_ATTEMPTS = 3


@dataclass
class Spec:
    """The model call an agent wants to make."""

    system: list[Block]
    prompt: str
    tool: Tool
    max_tokens: int


@dataclass
class Prepared:
    """What an agent's prepare decided. Exactly one of spec and result is set: result means there
    is nothing to generate (e.g. every capability already has a criterion) and the generation
    completes without calling the model. state is the agent's own context, handed back to apply."""

    spec: Spec | None = None
    result: Any = None
    state: Any = None


class InvalidAnswer(Exception):
    """A model answer the agent cannot use. `reason` is fed back to the model in the repair
    attempt, so it is phrased for the model."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"invalid answer: {reason}")
        self.reason = reason


class Agent(Protocol):
    name: str
    prompt_version: str

    async def prepare(self, conn: AsyncConnection, gen: dict) -> Prepared:
        """Read the context for a generation, inside a tenant transaction."""
        ...

    async def apply(self, conn: AsyncConnection, gen: dict, prepared: Prepared, answer: Any) -> Any:
        """Validate the model's answer against the current state of the database and store what
        passes, inside a tenant transaction. Returns the generation's result. An answer that
        cannot be used at all raises InvalidAnswer, which earns the model one repair attempt."""
        ...
