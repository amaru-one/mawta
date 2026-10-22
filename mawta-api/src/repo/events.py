"""The audit event writers."""

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from jsonutil import jsonb


async def log_event(
    conn: AsyncConnection[DictRow],
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    student_id: UUID | None = None,
    class_id: UUID | None = None,
    session_id: UUID | None = None,
) -> None:
    """Call the schema's app.log_event(...), which fills tenant/actor/request_id from the GUCs."""
    await conn.execute(
        "select app.log_event(%s, %s, %s::uuid, %s, %s::uuid, %s::uuid, %s::uuid)",
        (action, entity_type, entity_id, jsonb(payload or {}), student_id, class_id, session_id),
    )


async def log_student_reads(
    conn: AsyncConnection[DictRow],
    student_ids: list[UUID],
    teacher_id: UUID,
    class_id: UUID | None,
    session_id: UUID | None,
) -> None:
    """Bulk student.read events for every student in a roster/search response, in the
    same transaction as the read. Every read returning identifiable students needs one."""
    if not student_ids:
        return
    await conn.execute(
        """
        insert into events (tenant_id, actor_id, actor_teacher_id, action, entity_type, entity_id,
                            student_id, class_id, session_id, payload, request_id)
        select app.current_tenant_id(), app.current_actor_id(), %(teacher)s::uuid, 'student.read',
               'student', sid, sid, %(class)s::uuid, %(session)s::uuid, '{}'::jsonb,
               nullif(current_setting('app.request_id', true), '')
          from unnest(%(ids)s::uuid[]) as sid
        """,
        {"ids": student_ids, "teacher": teacher_id, "class": class_id, "session": session_id},
    )
