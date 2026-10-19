"""Enqueueing jobs."""

from uuid import UUID

from psycopg import AsyncConnection

from mawta_api.jsonutil import jsonb

_CONFLICT = """
    on conflict (kind, unique_key) where unique_key is not null
      and status in ('available','retryable','scheduled','running')
    do nothing
"""


async def enqueue_job(
    conn: AsyncConnection,
    tenant_id: UUID,
    kind: str,
    priority: int,
    payload: dict,
    unique_key: str = "",
    max_attempts: int | None = None,
) -> None:
    """Insert a job row, deduping against jobs_unique_key_idx when unique_key is non-empty.
    Runs inside the caller's tenant transaction so the enqueue is atomic with the write that
    triggered it. max_attempts overrides the column default (20) for jobs whose retries must
    stay few: a model call that keeps failing should fail its generation within seconds."""
    params = {
        "tenant": tenant_id,
        "kind": kind,
        "priority": priority,
        "payload": jsonb(payload),
        "unique_key": unique_key or None,
        "max_attempts": max_attempts,
    }
    if max_attempts is None:
        await conn.execute(
            """
            insert into jobs (tenant_id, kind, queue, priority, payload, unique_key)
            values (%(tenant)s, %(kind)s, 'default', %(priority)s::smallint, %(payload)s,
                    %(unique_key)s)
            """
            + _CONFLICT,
            params,
        )
        return
    await conn.execute(
        """
        insert into jobs (tenant_id, kind, queue, priority, payload, unique_key, max_attempts)
        values (%(tenant)s, %(kind)s, 'default', %(priority)s::smallint, %(payload)s,
                %(unique_key)s, %(max_attempts)s::smallint)
        """
        + _CONFLICT,
        params,
    )
