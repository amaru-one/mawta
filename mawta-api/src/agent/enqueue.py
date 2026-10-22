"""Start a generation."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from agent import JOB_KIND, MAX_ATTEMPTS
from repo import agent_generations as gens
from repo.events import log_event
from repo.jobs import enqueue_job

# How long a generation may take before it is shown as failed (agent_generations.deadline_at).
DEFAULT_DEADLINE = timedelta(minutes=5)


async def enqueue(
    conn: AsyncConnection[DictRow],
    tenant_id: UUID,
    *,
    deadline: timedelta | None = None,
    **fields,
) -> dict[str, Any]:
    """Record a generation and queue the job that runs it, in the caller's transaction, or return
    the one already in flight for the same target. Both the API ("✦ Generar con Mawta") and the
    worker (a voice note that finished transcribing queues its redaction sweep) start generations
    through here. `fields` are create_generation's: agent, kind, class_id, requested_by,
    target_key and the optional scope columns."""
    gen, created = await gens.create_generation(
        conn, deadline=deadline or DEFAULT_DEADLINE, **fields
    )
    if not created:
        return gen
    await enqueue_job(
        conn,
        tenant_id,
        JOB_KIND,
        2,
        {"generation_id": str(gen["id"])},
        f"{JOB_KIND}:{gen['id']}",
        MAX_ATTEMPTS,
    )
    await log_event(
        conn,
        "agent.generation.requested",
        "agent_generation",
        gen["id"],
        {"agent": gen["agent"], "kind": gen["kind"]},
        gen["student_id"],
        gen["class_id"],
    )
    return gen
