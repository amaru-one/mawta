"""Voice-note attribution and the redaction sweep's rows."""

from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from db import fetch_all, fetch_required
from errors import AppError, NotFound
from mawta_schema.tables import ClassSession, Student, VoiceNote, VoiceNoteRedaction

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
    conn: AsyncConnection, voice_note_id: UUID
) -> dict[str, Any]:
    """What the sweep reads of a live voice note: id, student_id, class_id, teacher_id,
    recorded_at, transcript, attribution_status. A discarded (deleted) note raises NotFound."""
    row = await fetch_required(
        conn,
        select(
            VoiceNote.id,
            VoiceNote.student_id,
            VoiceNote.class_id,
            VoiceNote.teacher_id,
            VoiceNote.recorded_at,
            VoiceNote.transcript,
            VoiceNote.attribution_status,
        ).where(VoiceNote.id == voice_note_id, VoiceNote.deleted_at.is_(None)),
    )
    return dict(row)


async def student_names(conn: AsyncConnection, ids: list[UUID]) -> list[dict[str, Any]]:
    """Names as the school recorded them, ordered by surname."""
    rows = await fetch_all(
        conn,
        select(
            Student.id,
            Student.given_name,
            Student.preferred_name,
            Student.paternal_surname,
            Student.maternal_surname,
        )
        .where(Student.id.in_(ids), Student.deleted_at.is_(None))
        .order_by(
            Student.paternal_surname, Student.maternal_surname, Student.given_name, Student.id
        ),
    )
    return [dict(r) for r in rows]


async def supersede_voice_note_redactions(conn: AsyncConnection, voice_note_id: UUID) -> None:
    """Close the live redaction rows of a note, before a new sweep writes its own."""
    await conn.execute(
        update(VoiceNoteRedaction)
        .where(
            VoiceNoteRedaction.voice_note_id == voice_note_id,
            VoiceNoteRedaction.superseded_at.is_(None),
        )
        .values(superseded_at=func.now())
    )


async def insert_voice_note_redaction(
    conn: AsyncConnection,
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
        insert(VoiceNoteRedaction).values(
            voice_note_id=voice_note_id,
            generation_id=generation_id,
            student_id=student_id,
            original_text=original_text,
            start_offset=start_offset,
            end_offset=end_offset,
            replacement=replacement,
            refers_to=refers_to,
            matched_student_id=matched_student_id,
            method="model",
        )
    )


def _live_note(voice_note_id: UUID):
    return update(VoiceNote).where(VoiceNote.id == voice_note_id, VoiceNote.deleted_at.is_(None))


async def set_voice_note_attribution(
    conn: AsyncConnection,
    voice_note_id: UUID,
    redacted: str | None,
    status: str,
    reason: str | None,
) -> None:
    """Record the outcome of a sweep or of a teacher's decision."""
    result = await conn.execute(
        _live_note(voice_note_id).values(
            transcript_redacted=redacted,
            attribution_status=status,
            discard_reason=reason,
            attribution_checked_at=func.now(),
        )
    )
    if result.rowcount == 0:
        raise NotFound


async def reassign_voice_note(conn: AsyncConnection, voice_note_id: UUID, student_id: UUID) -> None:
    """Move a note to another student and send it back to pending: its redacted transcript
    was built around the previous student, so it is cleared and the sweep runs again."""
    await supersede_voice_note_redactions(conn, voice_note_id)
    result = await conn.execute(
        _live_note(voice_note_id).values(
            student_id=student_id,
            transcript_redacted=None,
            attribution_status=ATTRIBUTION_PENDING,
            discard_reason=None,
            attribution_checked_at=func.now(),
        )
    )
    if result.rowcount == 0:
        raise NotFound


async def pending_voice_notes_for_student_term(
    conn: AsyncConnection, class_id: UUID, student_id: UUID, term_id: UUID
) -> list[UUID]:
    """Notes of a student in a class and term that the sweep has not processed yet:
    transcribed but still pending. Used to queue the sweep lazily for older notes."""
    result = await conn.execute(
        select(VoiceNote.id)
        .join(ClassSession, ClassSession.id == VoiceNote.session_id)
        .where(
            VoiceNote.class_id == class_id,
            VoiceNote.student_id == student_id,
            ClassSession.term_id == term_id,
            VoiceNote.deleted_at.is_(None),
            VoiceNote.transcription_status == "completed",
            VoiceNote.attribution_status == ATTRIBUTION_PENDING,
        )
    )
    return list(result.scalars())


async def confirm_voice_note(conn: AsyncConnection, voice_note_id: UUID) -> None:
    """A teacher kept a note the sweep discarded for naming other students. Anything else
    cannot be confirmed."""
    result = await conn.execute(
        _live_note(voice_note_id)
        .where(
            VoiceNote.attribution_status == ATTRIBUTION_DISCARDED,
            VoiceNote.discard_reason == DISCARD_MENTIONS_OTHER_STUDENT,
            VoiceNote.transcript_redacted.is_not(None),
        )
        .values(
            attribution_status=ATTRIBUTION_CONFIRMED,
            discard_reason=None,
            attribution_checked_at=func.now(),
        )
    )
    if result.rowcount == 0:
        raise AppError(
            422,
            "not_confirmable",
            "Esta nota no se puede confirmar: solo las descartadas por nombrar a otros estudiantes.",
        )
