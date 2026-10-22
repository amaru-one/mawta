"""Which handler runs which job kind."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow

import applog
import domain
from agent.llm import Prices
from agent.llm.anthropic import Anthropic
from agent.runner import Outcome, Runner
from stt import Client as SttClient
from web import Api
from worker.handlers.transcribe import AfterTranscript, voice_note_transcribe

# Job is the claimed row handed to a handler.


@dataclass
class Job:
    id: int
    tenant_id: Any  # UUID, or None for cross-tenant maintenance jobs
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


# Runs inside the job's tenant (or system) transaction.
InTxHandler = Callable[[AsyncConnection[DictRow], Job], Awaitable[None]]
# Manages its own transactions: for work that waits on something slow outside the database (a
# language-model call can take a minute) which must not hold a transaction, and its row locks,
# open while it waits.
OwnTxHandler = Callable[[Job], Awaitable[None]]


@dataclass
class Registry:
    in_tx: dict[str, InTxHandler] = field(default_factory=dict)
    own_tx: dict[str, OwnTxHandler] = field(default_factory=dict)


def agent_generate(runner: Runner) -> OwnTxHandler:
    """Adapt an agent runner to a job handler: a transient failure is raised so the queue retries
    it; a skipped or failed generation is final and reported as such, so the job is not retried."""

    async def handle(job: Job) -> None:
        outcome, err = await runner.run(job.tenant_id, job.payload, job.attempts, job.max_attempts)
        if err is not None:
            raise err
        if outcome == Outcome.SKIPPED:
            applog.report_outcome(applog.OUTCOME_SKIPPED, "generation_not_runnable")
        elif outcome == Outcome.FAILED:
            applog.report_outcome(applog.OUTCOME_PERMANENT_FAILURE, "generation_failed")

    return handle


def build_runner(api: Api) -> Runner:
    """The agents and the models they run on. planning runs on the default model; the redaction
    sweep and the conclusions agent each on their own, with their own prices."""
    from agent.conclusions import ConclusionsAgent
    from agent.planning import PlanningAgent
    from agent.redaction import RedactionAgent

    cfg = api.settings
    key = cfg.anthropic_api_key.get_secret_value()
    prices = Prices(**cfg.prices("planning").model_dump())
    runner = Runner(
        api.db,
        Anthropic(key, cfg.planning_agent_model, cfg.agent_timeout),
        prices,
        api.logger,
        PlanningAgent(),
    )
    runner.bind(
        RedactionAgent(),
        Anthropic(key, cfg.redaction_agent_model, cfg.agent_timeout),
        Prices(**cfg.prices("redaction").model_dump()),
    )
    runner.bind(
        ConclusionsAgent(),
        Anthropic(key, cfg.conclusions_agent_model, cfg.agent_timeout),
        Prices(**cfg.prices("conclusions").model_dump()),
    )
    return runner


def default_registry(api: Api, runner: Runner | None = None) -> Registry:
    """voice_note.transcribe needs an STT client (built once here, not per job); agent.generate
    runs Mawta's agents and manages its own transactions (OwnTx)."""
    cfg = api.settings
    stt_client = SttClient(
        cfg.transcribe_openrouter_api_key, cfg.transcribe_model, logger=api.logger
    )
    # A saved transcript queues its name sweep, but only when the agents can run: without a key
    # every sweep would fail, and the note simply stays pending until one is configured (the
    # conclusions endpoint queues pending notes again).
    after: list[AfterTranscript] = []
    if cfg.anthropic_api_key.get_secret_value():
        from agent.redaction import queue_after_transcript

        after.append(queue_after_transcript)
    transcribe = voice_note_transcribe(stt_client, *after)

    async def transcribe_job(conn: AsyncConnection[DictRow], job: Job) -> None:
        await transcribe(conn, job.id, job.payload)

    return Registry(
        in_tx={domain.JOB_KIND_VOICE_NOTE_TRANSCRIBE: transcribe_job},
        own_tx={domain.JOB_KIND_AGENT_GENERATE: agent_generate(runner or build_runner(api))},
    )
