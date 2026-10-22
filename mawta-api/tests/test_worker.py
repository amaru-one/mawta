"""The job queue: claiming, dispatch, retry bookkeeping and outcome events (port of the worker
tests)."""

import io
import logging
import uuid

import pytest

import applog
from db import Database
from tests.conftest import FX
from worker import claim, dispatch
from worker.registry import Job, Registry


@pytest.fixture
async def queue(client, admin):
    """A private queue name per test, so jobs of other tests are never claimed."""
    name = f"t-{uuid.uuid4().hex[:8]}"
    yield name
    await admin.execute("delete from jobs where queue = %s", (name,))


async def add_job(admin, queue, kind="voice_note.transcribe", max_attempts=3, priority=3):
    cur = await admin.execute(
        "insert into jobs (tenant_id, kind, queue, priority, payload, max_attempts)"
        " values (%s, %s, %s, %s, '{}', %s) returning id",
        (FX.tenant_a, kind, queue, priority, max_attempts),
    )
    return (await cur.fetchone())["id"]


async def job_row(admin, job_id):
    cur = await admin.execute(
        "select status, attempts, finalized_at, errors, run_after > now() as delayed"
        " from jobs where id = %s",
        (job_id,),
    )
    return await cur.fetchone()


def capture():
    stream = io.StringIO()
    return stream, applog.new_json_logger(logging.INFO, stream)


def outcomes(stream):
    import json

    return [
        json.loads(line)
        for line in stream.getvalue().splitlines()
        if '"worker.job_outcome"' in line
    ]


async def claim_one(db: Database, queue: str) -> Job:
    """claim(), in a test that has just queued the job it expects."""
    job = await claim(db, queue, "w1")
    assert job is not None
    return job


async def test_claim_takes_one_job_by_priority_and_marks_it_running(client, admin, queue):
    db = client.app.state.api.db
    low = await add_job(admin, queue, priority=3)
    high = await add_job(admin, queue, priority=1)
    job = await claim_one(db, queue)
    assert job.id == high and job.attempts == 1
    assert (await job_row(admin, high))["status"] == "running"
    assert (await job_row(admin, low))["status"] == "available"
    assert (await claim_one(db, queue)).id == low
    assert await claim(db, queue, "w1") is None


async def test_success_completes_the_job_and_emits_one_outcome(client, admin, queue):
    db = client.app.state.api.db
    job_id = await add_job(admin, queue)
    stream, logger = capture()

    async def ok(conn, job):
        return None

    job = await claim_one(db, queue)
    await dispatch(db, Registry(in_tx={"voice_note.transcribe": ok}), job, "w1", logger)
    row = await job_row(admin, job_id)
    assert row["status"] == "completed" and row["finalized_at"] is not None
    (event,) = outcomes(stream)
    assert event["outcome"] == "success" and event["task_id"] == job_id


async def test_failure_is_retried_with_backoff_then_discarded(client, admin, queue):
    db = client.app.state.api.db
    job_id = await add_job(admin, queue, max_attempts=2)
    stream, logger = capture()

    async def boom(conn, job):
        raise RuntimeError("boom")

    registry = Registry(in_tx={"voice_note.transcribe": boom})
    job = await claim_one(db, queue)
    await dispatch(db, registry, job, "w1", logger)
    row = await job_row(admin, job_id)
    assert row["status"] == "retryable" and row["delayed"] and row["errors"][0]["error"] == "boom"

    await admin.execute("update jobs set run_after = now() where id = %s", (job_id,))
    job = await claim_one(db, queue)
    assert job.attempts == 2
    await dispatch(db, registry, job, "w1", logger)
    assert (await job_row(admin, job_id))["status"] == "discarded"
    assert [e["outcome"] for e in outcomes(stream)] == ["retryable_failure", "permanent_failure"]


async def test_unknown_kind_fails_and_reported_outcomes_win_over_success(client, admin, queue):
    db = client.app.state.api.db
    unknown = await add_job(admin, queue, kind="no.such.kind")
    stream, logger = capture()
    job = await claim_one(db, queue)
    await dispatch(db, Registry(), job, "w1", logger)
    assert (await job_row(admin, unknown))["status"] == "retryable"
    assert outcomes(stream)[0]["reason"] == "unknown_kind"

    skipped = await add_job(admin, queue)

    async def skip(conn, job):
        applog.report_outcome(applog.OUTCOME_SKIPPED, "voice_note_discarded")

    job = await claim_one(db, queue)
    assert job.id == skipped
    await dispatch(db, Registry(in_tx={"voice_note.transcribe": skip}), job, "w1", logger)
    assert (await job_row(admin, skipped))["status"] == "completed"
    assert outcomes(stream)[-1]["outcome"] == "skipped"


def test_job_dataclass_defaults():
    assert Job(1, None, "k", {}, 1, 3).tenant_id is None
