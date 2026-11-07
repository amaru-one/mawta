"""agent_generations: one "✦ Generar con Mawta" request and its outcome. The agents share this
table: `agent` says which one serves the request and `kind` what it generates. Rows are dicts keyed
by column; jsonb columns arrive decoded."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Text, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_one, fetch_required
from errors import AppError
from mawta_schema.tables import AgentGeneration

GENERATION_PENDING = "pending"
GENERATION_RUNNING = "running"
GENERATION_COMPLETED = "completed"
GENERATION_FAILED = "failed"

# What a teacher reads when a generation ran past its deadline without finishing (a worker that
# died, a queue that stalled).
EXPIRED_GENERATION_MESSAGE = (
    "Mawta tardó demasiado en responder. Intenta de nuevo o escríbelo a mano."
)

G = AgentGeneration
_COLUMNS = (
    G.id,
    G.agent,
    G.kind,
    G.class_id,
    G.experience_id,
    G.student_id,
    G.competency_id,
    G.term_id,
    G.voice_note_id,
    G.requested_by,
    G.target_key,
    G.status,
    G.input,
    G.result,
    G.error,
    G.attempts,
    G.deadline_at,
    G.created_at,
    G.finished_at,
)
_IN_FLIGHT = (GENERATION_PENDING, GENERATION_RUNNING)


def expired(gen: dict[str, Any], now: datetime | None = None) -> bool:
    """An unfinished generation past its deadline. The API shows such a generation as failed and
    the worker never starts it."""
    now = now or datetime.now(UTC)
    return gen["status"] in (GENERATION_PENDING, GENERATION_RUNNING) and now > gen["deadline_at"]


@dataclass
class Usage:
    """The tokens the model calls of one attempt used. Added to the generation's totals, so retries
    are counted too."""

    model: str = ""
    prompt_version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def params(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "input": self.input_tokens,
            "output": self.output_tokens,
            "cache_read": self.cache_read_tokens,
            "cache_write": self.cache_write_tokens,
        }


def _add_usage(usage: Usage) -> dict[str, Any]:
    """The update values that add an attempt's usage to the generation's totals."""
    return {
        "model": func.coalesce(func.nullif(literal(usage.model, Text), ""), G.model),
        "prompt_version": func.coalesce(
            func.nullif(literal(usage.prompt_version, Text), ""), G.prompt_version
        ),
        "input_tokens": G.input_tokens + usage.input_tokens,
        "output_tokens": G.output_tokens + usage.output_tokens,
        "cache_read_tokens": G.cache_read_tokens + usage.cache_read_tokens,
        "cache_write_tokens": G.cache_write_tokens + usage.cache_write_tokens,
    }


async def create_generation(
    conn: AsyncConnection,
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
        pg_insert(G)
        .values(
            agent=agent,
            kind=kind,
            class_id=class_id,
            experience_id=experience_id,
            student_id=student_id,
            competency_id=competency_id,
            term_id=term_id,
            voice_note_id=voice_note_id,
            requested_by=requested_by,
            target_key=target_key,
            input=input if input is not None else {},
            deadline_at=func.now() + deadline,
        )
        .on_conflict_do_nothing(index_elements=[G.target_key], index_where=G.status.in_(_IN_FLIGHT))
        .returning(*_COLUMNS),
    )
    if row is not None:
        return dict(row), True
    existing = await fetch_required(
        conn, select(*_COLUMNS).where(G.target_key == target_key, G.status.in_(_IN_FLIGHT))
    )
    return dict(existing), False


async def get_generation(conn: AsyncConnection, generation_id: UUID) -> dict[str, Any]:
    row = await fetch_one(conn, select(*_COLUMNS).where(G.id == generation_id))
    if row is None:
        raise AppError(404, "not_found", "no se encontró la generación")
    return dict(row)


async def start_generation(
    conn: AsyncConnection, generation_id: UUID
) -> tuple[dict[str, Any] | None, bool]:
    """Claim a generation for one attempt: lock the row, move it to running and count the attempt.
    ok is False when there is nothing to do: the generation already finished, or it is past its
    deadline (then it is marked failed here, so it never runs late). Raises NotFound when the row
    does not exist."""
    gen = dict(
        await fetch_required(conn, select(*_COLUMNS).where(G.id == generation_id).with_for_update())
    )
    if gen["status"] not in _IN_FLIGHT:
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
        update(G)
        .where(G.id == generation_id)
        .values(
            status=GENERATION_RUNNING,
            attempts=G.attempts + 1,
            started_at=func.coalesce(G.started_at, func.now()),
        )
        .returning(*_COLUMNS),
    )
    return dict(started), True


async def record_generation_usage(conn: AsyncConnection, generation_id: UUID, usage: Usage) -> None:
    """Add an attempt's usage without finishing the generation: a transient failure that will be
    retried still used tokens."""
    await conn.execute(update(G).where(G.id == generation_id).values(**_add_usage(usage)))


async def complete_generation(
    conn: AsyncConnection, generation_id: UUID, result: object, usage: Usage
) -> None:
    await conn.execute(
        update(G)
        .where(G.id == generation_id)
        .values(
            status=GENERATION_COMPLETED,
            result=result,
            error=None,
            error_detail=None,
            finished_at=func.now(),
            **_add_usage(usage),
        )
    )


async def fail_generation(
    conn: AsyncConnection, generation_id: UUID, message: str, detail: str, usage: Usage
) -> None:
    """message is for the teacher and goes out in the API; detail is for support and never does."""
    await conn.execute(
        update(G)
        .where(G.id == generation_id)
        .values(
            status=GENERATION_FAILED,
            error=message,
            error_detail=detail or None,
            finished_at=func.now(),
            **_add_usage(usage),
        )
    )


async def latest_conclusion_generation(
    conn: AsyncConnection, student_id: UUID, competency_id: UUID, term_id: UUID
) -> dict[str, Any] | None:
    """The most recent conclusions generation for a student, competency and term, so a proposal
    survives a page reload."""
    row = await fetch_one(
        conn,
        select(*_COLUMNS)
        .where(
            G.agent == "conclusions",
            G.student_id == student_id,
            G.competency_id == competency_id,
            G.term_id == term_id,
        )
        .order_by(G.created_at.desc())
        .limit(1),
    )
    return dict(row) if row else None
