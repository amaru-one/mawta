"""Which handler runs which job kind."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow

import applog
import domain
from agent.llm.openai_compat import OpenAICompat
from agent.llm.providers import client_for
from agent.runner import Outcome, Runner
from settings import Settings
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


def agent_model(cfg: Settings, agent: str) -> OpenAICompat:
    """The model of one agent, from its own "provider:model" setting. Without a model, or without
    what its provider needs, the model has no client: the routes answer agent_unavailable and a
    generation that still reaches it fails permanently."""
    ref = cfg.agent_model(agent)
    if ref is None or not cfg.agent_ready(agent):
        return OpenAICompat(ref, None)
    client = client_for(ref, cfg.endpoints(), cfg.agent_timeout)
    return OpenAICompat(ref, client, cfg.agent_reasoning_effort(agent))


def build_runner(api: Api) -> Runner:
    """Every agent with the model it runs on: each has its own, so the name sweep can run on a
    small model and the conclusions on a larger one."""
    from agent.conclusions import ConclusionsAgent
    from agent.planning import PlanningAgent
    from agent.redaction import RedactionAgent

    cfg = api.settings
    runner = Runner(api.db, api.logger)
    for agent in (PlanningAgent(), RedactionAgent(), ConclusionsAgent()):
        runner.bind(agent, agent_model(cfg, agent.name))
    return runner


def default_registry(api: Api, runner: Runner | None = None) -> Registry:
    """voice_note.transcribe needs an STT client (built once here, not per job); agent.generate
    runs Mawta's agents and manages its own transactions (OwnTx)."""
    cfg = api.settings
    stt_client = SttClient(
        cfg.transcribe_openrouter_api_key, cfg.transcribe_model, logger=api.logger
    )
    # A saved transcript queues its name sweep, but only when the sweep has a model: without one
    # every sweep would fail, and the note simply stays pending until one is configured (the
    # conclusions endpoint queues pending notes again).
    after: list[AfterTranscript] = []
    if cfg.agent_ready("redaction"):
        from agent.redaction import queue_after_transcript

        after.append(queue_after_transcript)
    transcribe = voice_note_transcribe(stt_client, *after)

    async def transcribe_job(conn: AsyncConnection[DictRow], job: Job) -> None:
        await transcribe(conn, job.id, job.payload)

    return Registry(
        in_tx={domain.JOB_KIND_VOICE_NOTE_TRANSCRIBE: transcribe_job},
        own_tx={domain.JOB_KIND_AGENT_GENERATE: agent_generate(runner or build_runner(api))},
    )
