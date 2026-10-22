"""The in-process background job processor (port of internal/worker).

A SELECT ... FOR UPDATE SKIP LOCKED claim loop over the jobs table, a handler registry keyed by
job kind, and exponential-backoff retry bookkeeping. Isolated behind run_worker so it could later
become its own process without touching the HTTP layer.

Every attempt emits a start event and exactly one terminal outcome event (success,
retryable_failure, permanent_failure, or skipped), both carrying task_id (the queue job id, the
same integer the jobs table carries) plus the job kind, attempt number, max attempts, worker name
and the terminal duration. The outcome event is emitted only after the attempt's persistence has
succeeded or failed, never before: a claim, transaction or persistence failure stays visible as
its own outcome.
"""

import asyncio
import contextlib
import logging
import math
import socket
import time
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb

import applog
from db import Database, TenantCtx
from web import Api
from worker.registry import Job, Registry, default_registry

POLL_INTERVAL = 2.0  # seconds


async def run_worker(api: Api, registry: Registry | None = None) -> None:
    """Run settings.worker_concurrency poll loops until cancelled."""
    registry = registry or default_registry(api)
    worker_name = socket.gethostname() or "worker"
    n = max(api.settings.worker_concurrency, 1)
    loops = [
        asyncio.create_task(
            poll_loop(api.db, api.settings.worker_queue, worker_name, registry, api.logger)
        )
        for _ in range(n)
    ]
    try:
        await asyncio.gather(*loops)
    finally:
        for task in loops:
            task.cancel()
        for task in loops:
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def poll_loop(
    database: Database, queue: str, worker_name: str, registry: Registry, logger: logging.Logger
) -> None:
    while True:
        try:
            job = await claim(database, queue, worker_name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            applog.error(logger, "worker: claim", error=str(exc))
            await asyncio.sleep(POLL_INTERVAL)
            continue
        if job is None:
            await asyncio.sleep(POLL_INTERVAL)
            continue
        await dispatch(database, registry, job, worker_name, logger)


async def claim(database: Database, queue: str, worker_name: str) -> Job | None:
    async with database.pool.connection() as conn:
        cur = await conn.execute(
            """
            update jobs
               set status = 'running', attempts = attempts + 1, attempted_at = now(),
                   attempted_by = %(worker)s
             where id = (
               select id from jobs
                where queue = %(queue)s and status in ('available','retryable','scheduled')
                  and run_after <= now()
                order by priority, run_after, id
                for update skip locked
                limit 1
             )
            returning id, tenant_id, kind, payload, attempts, max_attempts
            """,
            {"worker": worker_name, "queue": queue},
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return Job(
        id=row["id"],
        tenant_id=row["tenant_id"],
        kind=row["kind"],
        payload=row["payload"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
    )


async def dispatch(
    database: Database, registry: Registry, job: Job, worker_name: str, logger: logging.Logger
) -> None:
    """Run one claimed job to a terminal outcome: emit the start event, run the handler inside the
    job's transaction, persist the outcome, and only then emit the terminal outcome event, so the
    event never claims a completion the database has not recorded."""
    start = time.monotonic()
    common: dict[str, Any] = {
        "task_id": job.id,
        "kind": job.kind,
        "attempt": job.attempts,
        "max_attempts": job.max_attempts,
        "worker": worker_name,
    }
    applog.log_job_start(logger, **common)

    def emit(outcome: str, reason: str = "", error_text: str = "") -> None:
        applog.log_job_outcome(
            logger,
            outcome=outcome,
            reason=reason,
            error_text=error_text,
            duration_ms=int((time.monotonic() - start) * 1000),
            **common,
        )

    async def fail(reason: str, cause: Exception) -> None:
        """Persist a failed attempt, then report it with the outcome the queue will actually
        apply: retried while attempts remain, discarded (a permanent failure) on the last one or
        when it cannot be recorded."""
        outcome = (
            applog.OUTCOME_PERMANENT_FAILURE
            if job.attempts >= job.max_attempts
            else applog.OUTCOME_RETRYABLE_FAILURE
        )
        error_text = applog.sanitize_error_cause(cause)
        try:
            await persist_failure(database, job, str(cause), logger)
        except Exception as exc:
            # Unrecorded, the job stays running and is never claimed again.
            outcome, reason = applog.OUTCOME_PERMANENT_FAILURE, "persistence_error"
            error_text = applog.sanitize_error_cause(exc)
        emit(outcome, reason, error_text)

    in_tx = registry.in_tx.get(job.kind)
    own_tx = registry.own_tx.get(job.kind)
    if in_tx is None and own_tx is None:
        await fail("unknown_kind", RuntimeError(f"unknown job kind: {job.kind}"))
        return

    # The task identity rides the context so the STT client can log usage against the right
    # task_id/attempt, and the handler can report an attempt that finished without doing its work.
    stt_token = applog.set_stt_task(applog.STTTask(job.id, job.attempts))
    report, report_token = applog.begin_outcome_report()
    try:
        if own_tx is not None:
            await own_tx(job)
        elif job.tenant_id is not None:
            tc = TenantCtx(tenant_id=job.tenant_id, request_id=f"job:{job.kind}")
            async with database.tenant_tx(tc) as conn:
                assert in_tx is not None
                await in_tx(conn, job)
        else:
            async with database.system_tx() as conn:
                assert in_tx is not None
                await in_tx(conn, job)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await fail("handler_error", exc)
        return
    finally:
        applog.end_outcome_report(report_token)
        applog.reset_stt_task(stt_token)

    # The handler's transaction committed; the job is only complete once its status is recorded.
    # A job whose completion cannot be recorded stays running and is never claimed again, so it is
    # reported as a permanent failure, never as a success.
    try:
        await persist_success(database, job)
    except Exception as exc:
        applog.error(
            logger,
            "worker: record success",
            task_id=job.id,
            job_id=job.id,
            error=applog.sanitize_error_cause(exc),
        )
        emit(
            applog.OUTCOME_PERMANENT_FAILURE, "persistence_error", applog.sanitize_error_cause(exc)
        )
        return
    if report.outcome:
        emit(report.outcome, report.reason)
        return
    emit(applog.OUTCOME_SUCCESS)


async def persist_success(database: Database, job: Job) -> None:
    async with database.pool.connection() as conn:
        await conn.execute(
            "update jobs set status = 'completed', finalized_at = now() where id = %s", (job.id,)
        )


async def persist_failure(
    database: Database, job: Job, error_message: str, logger: logging.Logger
) -> None:
    """The retry/discard bookkeeping: backoff min(attempts^4, 3600) seconds, discarded once
    attempts reach max_attempts."""
    record = {
        "attempt": job.attempts,
        "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "error": error_message[:2000],
    }
    backoff = min(math.pow(job.attempts, 4), 3600)
    try:
        async with database.pool.connection() as conn:
            await conn.execute(
                """
                update jobs set
                  status = case when attempts >= max_attempts then 'discarded' else 'retryable' end,
                  finalized_at = case when attempts >= max_attempts then now() end,
                  run_after = now() + make_interval(secs => %(backoff)s),
                  errors = errors || jsonb_build_array(%(record)s::jsonb)
                where id = %(id)s
                """,
                {"id": job.id, "backoff": backoff, "record": Jsonb(record)},
            )
    except Exception as exc:
        applog.error(
            logger,
            "worker: record failure",
            task_id=job.id,
            job_id=job.id,
            error=applog.sanitize_error_cause(exc),
        )
        raise
