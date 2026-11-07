"""The audit event writers."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncConnection

from mawta_schema.tables import Event

_UUID = PgUUID(as_uuid=True)


async def log_event(
    conn: AsyncConnection,
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    student_id: UUID | None = None,
    class_id: UUID | None = None,
    session_id: UUID | None = None,
) -> None:
    """Call the schema's app.log_event(...), which fills actor and request id from the
    transaction's settings."""
    await conn.execute(
        select(
            func.app.log_event(
                action,
                entity_type,
                literal(entity_id, _UUID),
                literal(payload or {}, JSONB),
                literal(student_id, _UUID),
                literal(class_id, _UUID),
                literal(session_id, _UUID),
            )
        )
    )


async def log_student_reads(
    conn: AsyncConnection,
    student_ids: list[UUID],
    teacher_id: UUID,
    class_id: UUID | None,
    session_id: UUID | None,
) -> None:
    """Bulk student.read events for every student in a roster/search response, in the
    same transaction as the read. Every read returning identifiable students needs one."""
    if not student_ids:
        return
    request_id = func.nullif(func.current_setting("app.request_id", True), "")
    await conn.execute(
        insert(Event).values(
            [
                {
                    "actor_id": func.app.current_actor_id(),
                    "actor_teacher_id": teacher_id,
                    "action": "student.read",
                    "entity_type": "student",
                    "entity_id": sid,
                    "student_id": sid,
                    "class_id": class_id,
                    "session_id": session_id,
                    "payload": {},
                    "request_id": request_id,
                }
                for sid in student_ids
            ]
        )
    )
