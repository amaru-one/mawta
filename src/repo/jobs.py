"""Enqueueing jobs."""

from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from mawta_schema.tables import Job

_LIVE = ("available", "retryable", "scheduled", "running")


async def enqueue_job(
    conn: AsyncConnection,
    kind: str,
    priority: int,
    payload: dict[str, Any],
    unique_key: str = "",
    max_attempts: int | None = None,
) -> None:
    """Insert a job row, deduping against jobs_unique_key_idx when unique_key is non-empty.
    Runs inside the caller's transaction so the enqueue is atomic with the write that
    triggered it. max_attempts overrides the column default (20) for jobs whose retries must
    stay few: a model call that keeps failing should fail its generation within seconds."""
    values: dict[str, Any] = {
        "kind": kind,
        "queue": "default",
        "priority": priority,
        "payload": payload,
        "unique_key": unique_key or None,
    }
    if max_attempts is not None:
        values["max_attempts"] = max_attempts
    await conn.execute(
        pg_insert(Job)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[Job.kind, Job.unique_key],
            index_where=Job.unique_key.is_not(None) & Job.status.in_(_LIVE),
        )
    )
