"""agent_generations: one "✦ Generar con Mawta" request and its outcome. The agents share this
table: `agent` says which one serves the request and `kind` what it generates. Rows are dicts keyed
by column; jsonb columns arrive decoded."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from db import fetch_one, fetch_required
from errors import AppError
from jsonutil import jsonb

GENERATION_PENDING = "pending"
GENERATION_RUNNING = "running"
GENERATION_COMPLETED = "completed"
GENERATION_FAILED = "failed"

# What a teacher reads when a generation ran past its deadline without finishing (a worker that
# died, a queue that stalled).
EXPIRED_GENERATION_MESSAGE = (
    "Mawta tardó demasiado en responder. Intenta de nuevo o escríbelo a mano."
)

_COLUMNS = """
    id, agent, kind, class_id, experience_id, student_id, competency_id, term_id, voice_note_id,
    requested_by, target_key, status, input, result, error, attempts, deadline_at, created_at,
    finished_at"""


def expired(gen: dict[str, Any], now: datetime | None = None) -> bool:
    """An unfinished generation past its deadline. The API shows such a generation as failed and
    the worker never starts it."""
    now = now or datetime.now(UTC)
    return gen["status"] in (GENERATION_PENDING, GENERATION_RUNNING) and now > gen["deadline_at"]


@dataclass
class Usage:
    """What the model calls of one attempt cost. Added to the generation's totals, so retries
    are counted too."""

    model: str = ""
    prompt_version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0

    def params(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "input": self.input_tokens,
            "output": self.output_tokens,
            "cache_read": self.cache_read_tokens,
            "cache_write": self.cache_write_tokens,
            "cost": self.cost_usd,
        }


_ADD_USAGE = """
    model = coalesce(nullif(%(model)s::text, ''), model),
    prompt_version = coalesce(nullif(%(prompt_version)s::text, ''), prompt_version),
    input_tokens = input_tokens + %(input)s,
    output_tokens = output_tokens + %(output)s,
    cache_read_tokens = cache_read_tokens + %(cache_read)s,
    cache_write_tokens = cache_write_tokens + %(cache_write)s,
    cost_usd = cost_usd + %(cost)s"""


async def create_generation(
    conn: AsyncConnection[DictRow],
    *,
    agent: str,
    kind: str,
    class_id: UUID,
    requested_by: UUID,
    target_key: str,
    deadline: timedelta,
    experience_id: UUID | None = None,
    student_id: UUID | None = None,
    competency_id: UUID | None = None,
    term_id: UUID | None = None,
    voice_note_id: UUID | None = None,
    input: dict[str, Any] | None = None,  # noqa: A002
) -> tuple[dict[str, Any], bool]:
    """Record a request, or return the one already in flight for the same target
    (agent_generations_target_key): asking twice for the same thing while it runs never starts a
    second generation. The bool says whether a new row was written, so the caller only enqueues a
    job for it."""
    row = await fetch_one(
        conn,
        f"""
        insert into agent_generations
          (tenant_id, agent, kind, class_id, experience_id, student_id, competency_id, term_id,
           voice_note_id, requested_by, target_key, input, deadline_at)
        values (app.current_tenant_id(), %(agent)s, %(kind)s, %(class)s, %(exp)s, %(student)s,
                %(comp)s, %(term)s, %(note)s, %(by)s, %(key)s, %(input)s,
                now() + make_interval(secs => %(secs)s))
        on conflict (tenant_id, target_key) where status in ('pending', 'running') do nothing
        returning {_COLUMNS}
        """,
        {
            "agent": agent,
            "kind": kind,
            "class": class_id,
            "exp": experience_id,
            "student": student_id,
            "comp": competency_id,
            "term": term_id,
            "note": voice_note_id,
            "by": requested_by,
            "key": target_key,
            "input": jsonb(input if input is not None else {}),
            "secs": deadline.total_seconds(),
        },
    )
    if row is not None:
        return row, True
    existing = await fetch_required(
        conn,
        f"""
        select {_COLUMNS} from agent_generations
         where target_key = %s and status in ('pending', 'running')
        """,
        (target_key,),
    )
    return existing, False


async def get_generation(conn: AsyncConnection[DictRow], generation_id: UUID) -> dict[str, Any]:
    """RLS hides other schools' rows, which surface as not_found."""
    row = await fetch_one(
        conn, f"select {_COLUMNS} from agent_generations where id = %s", (generation_id,)
    )
    if row is None:
        raise AppError(404, "not_found", "no se encontró la generación")
    return row


async def start_generation(
    conn: AsyncConnection[DictRow], generation_id: UUID
) -> tuple[dict[str, Any] | None, bool]:
    """Claim a generation for one attempt: lock the row, move it to running and count the attempt.
    ok is False when there is nothing to do: the generation already finished, or it is past its
    deadline (then it is marked failed here, so it never runs late). Raises NotFound when the row
    does not exist."""
    gen = await fetch_required(
        conn,
        f"select {_COLUMNS} from agent_generations where id = %s for update",
        (generation_id,),
    )
    if gen["status"] not in (GENERATION_PENDING, GENERATION_RUNNING):
        return gen, False
    if expired(gen):
        await fail_generation(
            conn,
            generation_id,
            EXPIRED_GENERATION_MESSAGE,
            "deadline passed before the attempt started",
            Usage(),
        )
        return gen, False
    started = await fetch_required(
        conn,
        f"""
        update agent_generations
           set status = 'running', attempts = attempts + 1, started_at = coalesce(started_at, now())
         where id = %s
        returning {_COLUMNS}
        """,
        (generation_id,),
    )
    return started, True


async def record_generation_usage(
    conn: AsyncConnection[DictRow], generation_id: UUID, usage: Usage
) -> None:
    """Add an attempt's usage without finishing the generation: a transient failure that will be
    retried still cost money."""
    await conn.execute(
        f"update agent_generations set {_ADD_USAGE} where id = %(id)s",
        {**usage.params(), "id": generation_id},
    )


async def complete_generation(
    conn: AsyncConnection[DictRow], generation_id: UUID, result: object, usage: Usage
) -> None:
    await conn.execute(
        f"""
        update agent_generations
           set status = 'completed', result = %(result)s, error = null, error_detail = null,
               finished_at = now(), {_ADD_USAGE}
         where id = %(id)s
        """,
        {**usage.params(), "id": generation_id, "result": jsonb(result)},
    )


async def fail_generation(
    conn: AsyncConnection[DictRow], generation_id: UUID, message: str, detail: str, usage: Usage
) -> None:
    """message is for the teacher and goes out in the API; detail is for support and never does."""
    await conn.execute(
        f"""
        update agent_generations
           set status = 'failed', error = %(message)s, error_detail = nullif(%(detail)s::text, ''),
               finished_at = now(), {_ADD_USAGE}
         where id = %(id)s
        """,
        {**usage.params(), "id": generation_id, "message": message, "detail": detail},
    )


async def latest_conclusion_generation(
    conn: AsyncConnection[DictRow], student_id: UUID, competency_id: UUID, term_id: UUID
) -> dict[str, Any] | None:
    """The most recent conclusions generation for a student, competency and term, so a proposal
    survives a page reload."""
    return await fetch_one(
        conn,
        f"""
        select {_COLUMNS} from agent_generations
         where agent = 'conclusions' and student_id = %s and competency_id = %s and term_id = %s
         order by created_at desc
         limit 1
        """,
        (student_id, competency_id, term_id),
    )
