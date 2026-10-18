"""Start a generation."""

from datetime import timedelta
from uuid import UUID

from psycopg import AsyncConnection

from mawta_api.agent import JOB_KIND, MAX_ATTEMPTS
from mawta_api.repo import agent_generations as gens
from mawta_api.repo.events import log_event
from mawta_api.repo.jobs import enqueue_job

# How long a generation may take before it is shown as failed (agent_generations.deadline_at).
DEFAULT_DEADLINE = timedelta(minutes=5)


async def enqueue(
    conn: AsyncConnection,
    tenant_id: UUID,
    *,
    deadline: timedelta | None = None,
    **fields,
) -> dict:
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
