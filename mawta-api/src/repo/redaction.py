"""Voice-note attribution and the redaction sweep's rows."""

from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import DictRow

from db import fetch_all, fetch_required
from errors import AppError, NotFound

# voice_notes.attribution_status
ATTRIBUTION_PENDING = "pending"
ATTRIBUTION_OK = "ok"
ATTRIBUTION_DISCARDED = "discarded"
ATTRIBUTION_CONFIRMED = "confirmed"
ATTRIBUTION_REASSIGNED = "reassigned"

# voice_notes.discard_reason
DISCARD_MENTIONS_OTHER_STUDENT = "mentions_other_student"
DISCARD_UNREADABLE = "unreadable"

# voice_note_redactions.refers_to
REFERS_TO_ASSIGNED_STUDENT = "assigned_student"
REFERS_TO_CLASSMATE = "classmate"
REFERS_TO_OTHER_PERSON = "other_person"


async def get_voice_note_for_redaction(
    conn: AsyncConnection[DictRow], voice_note_id: UUID
) -> dict[str, Any]:
    """What the sweep reads of a live voice note: id, student_id, class_id, teacher_id,
    recorded_at, transcript, attribution_status. A discarded (deleted) note raises NotFound."""
    return await fetch_required(
        conn,
        """
        select id, student_id, class_id, teacher_id, recorded_at, transcript, attribution_status
          from voice_notes where id = %s and deleted_at is null
        """,
        (voice_note_id,),
    )


async def student_names(conn: AsyncConnection[DictRow], ids: list[UUID]) -> list[dict[str, Any]]:
    """Names as the school recorded them, ordered by surname."""
    return await fetch_all(
        conn,
        """
        select id, given_name, preferred_name, paternal_surname, maternal_surname
          from students where id = any(%s::uuid[]) and deleted_at is null
         order by paternal_surname, maternal_surname, given_name, id
        """,
        (ids,),
    )


async def supersede_voice_note_redactions(
    conn: AsyncConnection[DictRow], voice_note_id: UUID
) -> None:
    """Close the live redaction rows of a note, before a new sweep writes its own."""
    await conn.execute(
        """
        update voice_note_redactions set superseded_at = now()
         where voice_note_id = %s and superseded_at is null
        """,
        (voice_note_id,),
    )


async def insert_voice_note_redaction(
    conn: AsyncConnection[DictRow],
    *,
    voice_note_id: UUID,
    generation_id: UUID,
    student_id: UUID,
    original_text: str,
    start_offset: int,
    end_offset: int,
    replacement: str,
    refers_to: str,
    matched_student_id: UUID | None,
) -> None:
    await conn.execute(
        """
        insert into voice_note_redactions
          (tenant_id, voice_note_id, generation_id, student_id, original_text,
           start_offset, end_offset, replacement, refers_to, matched_student_id, method)
        values (app.current_tenant_id(), %s, %s, %s, %s, %s, %s, %s, %s, %s, 'model')
        """,
        (
            voice_note_id,
            generation_id,
            student_id,
            original_text,
            start_offset,
            end_offset,
            replacement,
            refers_to,
            matched_student_id,
        ),
    )


async def set_voice_note_attribution(
    conn: AsyncConnection[DictRow],
    voice_note_id: UUID,
    redacted: str | None,
    status: str,
    reason: str | None,
) -> None:
    """Record the outcome of a sweep or of a teacher's decision."""
    cur = await conn.execute(
        """
        update voice_notes
           set transcript_redacted = %s, attribution_status = %s, discard_reason = %s,
               attribution_checked_at = now()
         where id = %s and deleted_at is null
        """,
        (redacted, status, reason, voice_note_id),
    )
    if cur.rowcount == 0:
        raise NotFound


async def reassign_voice_note(
    conn: AsyncConnection[DictRow], voice_note_id: UUID, student_id: UUID
) -> None:
    """Move a note to another student and send it back to pending: its redacted transcript
    was built around the previous student, so it is cleared and the sweep runs again."""
    await supersede_voice_note_redactions(conn, voice_note_id)
    cur = await conn.execute(
        """
        update voice_notes
           set student_id = %s, transcript_redacted = null, attribution_status = 'pending',
               discard_reason = null, attribution_checked_at = now()
         where id = %s and deleted_at is null
        """,
        (student_id, voice_note_id),
    )
    if cur.rowcount == 0:
        raise NotFound


async def pending_voice_notes_for_student_term(
    conn: AsyncConnection[DictRow], class_id: UUID, student_id: UUID, term_id: UUID
) -> list[UUID]:
    """Notes of a student in a class and term that the sweep has not processed yet:
    transcribed but still pending. Used to queue the sweep lazily for older notes."""
    rows = await fetch_all(
        conn,
        """
        select vn.id
          from voice_notes vn
          join class_sessions cs on cs.id = vn.session_id
         where vn.class_id = %s and vn.student_id = %s and cs.term_id = %s
           and vn.deleted_at is null
           and vn.transcription_status = 'completed'
           and vn.attribution_status = 'pending'
        """,
        (class_id, student_id, term_id),
    )
    return [r["id"] for r in rows]


async def confirm_voice_note(conn: AsyncConnection[DictRow], voice_note_id: UUID) -> None:
    """A teacher kept a note the sweep discarded for naming other students. Anything else
    cannot be confirmed."""
    cur = await conn.execute(
        """
        update voice_notes
           set attribution_status = 'confirmed', discard_reason = null,
               attribution_checked_at = now()
         where id = %s and deleted_at is null
           and attribution_status = 'discarded' and discard_reason = 'mentions_other_student'
           and transcript_redacted is not null
        """,
        (voice_note_id,),
    )
    if cur.rowcount == 0:
        raise AppError(
            422,
            "not_confirmable",
            "Esta nota no se puede confirmar: solo las descartadas por nombrar a otros estudiantes.",
        )


async def current_tenant_id(conn: AsyncConnection[DictRow]) -> UUID:
    row = await fetch_required(conn, "select app.current_tenant_id() as id")
    return row["id"]
