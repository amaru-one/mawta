"""Class sessions, attendance, voice notes, notifications."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Executable,
    SQLColumnExpression,
    Text,
    case,
    func,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

import domain
from db import fetch_all, fetch_required, scalar
from errors import NotFound
from mawta_schema.tables import (
    AttendanceRecord,
    Class,
    ClassSession,
    Notification,
    SectionMembership,
    Student,
    VoiceNote,
)
from repo.roster import roster_as_of


async def get_session_header(conn: AsyncConnection, session_id: UUID) -> dict[str, Any]:
    h = await fetch_required(
        conn,
        select(
            ClassSession.id.label("session_id"),
            ClassSession.class_id,
            Class.name.label("class_name"),
            ClassSession.term_id,
            ClassSession.topic,
            ClassSession.session_date,
            ClassSession.status,
        )
        .join(Class, Class.id == ClassSession.class_id)
        .where(ClassSession.id == session_id, ClassSession.deleted_at.is_(None)),
    )
    roster = await roster_as_of(conn, h["class_id"], h["session_date"])
    marked = await scalar(
        conn,
        select(func.count()).where(
            AttendanceRecord.session_id == session_id, AttendanceRecord.deleted_at.is_(None)
        ),
    )
    return {
        "session_id": h["session_id"],
        "class_id": h["class_id"],
        "class_name": h["class_name"],
        "term_id": h["term_id"],
        "topic": h["topic"],
        "session_date": h["session_date"].isoformat(),
        "status": h["status"],
        "attendance_marked": marked,
        "attendance_total": len(roster),
    }


def _on_date(d: date | SQLColumnExpression[date]):
    return (
        SectionMembership.joined_on <= d,
        or_(SectionMembership.left_on.is_(None), SectionMembership.left_on > d),
        SectionMembership.deleted_at.is_(None),
    )


async def start_session(conn: AsyncConnection, session_id: UUID, teacher_id: UUID) -> bool:
    """Move a scheduled session to in progress. False when it was not scheduled."""
    result = await conn.execute(
        update(ClassSession)
        .where(
            ClassSession.id == session_id,
            ClassSession.status == domain.SESSION_SCHEDULED,
            ClassSession.deleted_at.is_(None),
        )
        .values(
            status=domain.SESSION_IN_PROGRESS,
            actual_start_at=func.now(),
            started_by_id=teacher_id,
        )
    )
    return result.rowcount > 0


async def get_session_roster(
    conn: AsyncConnection, session_id: UUID, class_id: UUID, session_date: date, q: str
) -> tuple[list[dict[str, Any]] | None, list[UUID]]:
    """The roster-as-of-session_date for a lesson screen, optionally filtered by a name
    substring. Returns the roster (None when empty: the UI expects null) and the ordered
    student ids, so the caller can log student.read events in the same transaction."""
    search = []
    if q:
        full = (
            func.coalesce(Student.given_name, "")
            + " "
            + func.coalesce(Student.paternal_surname, "")
            + " "
            + func.coalesce(Student.maternal_surname, "")
        )
        search.append(full.ilike(literal("%", Text) + q + "%"))
    rows = await fetch_all(
        conn,
        select(
            Student.id.label("student_id"),
            (
                func.coalesce(Student.preferred_name, Student.given_name)
                + " "
                + Student.paternal_surname
            ).label("name"),
            AttendanceRecord.status.label("attendance_status"),
        )
        .select_from(SectionMembership)
        .join(Class, (Class.section_id == SectionMembership.section_id) & (Class.id == class_id))
        .join(Student, (Student.id == SectionMembership.student_id) & Student.deleted_at.is_(None))
        .outerjoin(
            AttendanceRecord,
            (AttendanceRecord.session_id == session_id)
            & (AttendanceRecord.student_id == Student.id)
            & AttendanceRecord.deleted_at.is_(None),
        )
        .where(*_on_date(session_date), *search)
        .order_by(Student.paternal_surname, Student.given_name),
    )
    notes = await fetch_all(
        conn,
        select(VoiceNote.student_id, VoiceNote.id, VoiceNote.duration_ms, VoiceNote.transcript)
        .where(VoiceNote.session_id == session_id, VoiceNote.deleted_at.is_(None))
        .order_by(VoiceNote.recorded_at),
    )
    by_student: dict[UUID, list[dict[str, Any]]] = {}
    for n in notes:
        by_student.setdefault(n["student_id"], []).append(
            {"id": n["id"], "duration_ms": n["duration_ms"], "transcript": n["transcript"]}
        )
    roster = [
        {
            "student_id": r["student_id"],
            "name": r["name"],
            "attendance_status": r["attendance_status"],
            "voice_notes": by_student.get(r["student_id"]),
        }
        for r in rows
    ]
    return (roster or None), [r["student_id"] for r in rows]


# ── attendance ──────────────────────────────────────────────────────────


async def get_session_meta(conn: AsyncConnection, session_id: UUID) -> tuple[UUID, date]:
    """The class and calendar date of a session: the minimum needed to compute its roster."""
    row = await fetch_required(
        conn,
        select(ClassSession.class_id, ClassSession.session_date).where(
            ClassSession.id == session_id, ClassSession.deleted_at.is_(None)
        ),
    )
    return row["class_id"], row["session_date"]


_ONE_PER_STUDENT = {
    "index_elements": [AttendanceRecord.session_id, AttendanceRecord.student_id],
    "index_where": AttendanceRecord.deleted_at.is_(None),
}


async def upsert_attendance(
    conn: AsyncConnection,
    session_id: UUID,
    student_id: UUID,
    teacher_id: UUID,
    status: str,
    minutes_late: int | None,
    note: str | None,
) -> None:
    """Denormalized columns (class_id, session_date) are filled by the sync_denormalised trigger."""
    stmt = pg_insert(AttendanceRecord).values(
        session_id=session_id,
        student_id=student_id,
        status=status,
        minutes_late=minutes_late,
        note=note,
        source="manual",
        recorded_by_id=teacher_id,
    )
    await conn.execute(
        stmt.on_conflict_do_update(
            **_ONE_PER_STUDENT,
            set_={
                "status": stmt.excluded.status,
                "minutes_late": stmt.excluded.minutes_late,
                "note": stmt.excluded.note,
                "source": "manual",
                "recorded_by_id": stmt.excluded.recorded_by_id,
                "recorded_at": func.now(),
            },
        )
    )


async def mark_all_present(
    conn: AsyncConnection,
    session_id: UUID,
    class_id: UUID,
    teacher_id: UUID,
    session_date: date,
) -> int:
    """A 'present' row for every roster student with no attendance row yet, without clobbering
    explicit marks already taken."""
    roster = (
        select(
            literal(session_id),
            SectionMembership.student_id,
            literal("present"),
            literal("bulk"),
            literal(teacher_id),
        )
        .join(Class, Class.section_id == SectionMembership.section_id)
        .where(Class.id == class_id, *_on_date(session_date))
    )
    # Counted through RETURNING: an INSERT ... SELECT does not report a reliable rowcount.
    result = await conn.execute(
        pg_insert(AttendanceRecord)
        .from_select(["session_id", "student_id", "status", "source", "recorded_by_id"], roster)
        .on_conflict_do_nothing(**_ONE_PER_STUDENT)
        .returning(AttendanceRecord.id)
    )
    return len(result.all())


async def maybe_stamp_attendance_taken(
    conn: AsyncConnection, session_id: UUID, teacher_id: UUID
) -> None:
    """Set attendance_taken_at/_by once every roster student as of the session date has a row."""
    marked = (
        select(func.count())
        .where(
            AttendanceRecord.session_id == ClassSession.id, AttendanceRecord.deleted_at.is_(None)
        )
        .scalar_subquery()
    )
    expected = (
        select(func.count())
        .select_from(SectionMembership)
        .join(Class, Class.section_id == SectionMembership.section_id)
        .where(Class.id == ClassSession.class_id, *_on_date(ClassSession.session_date))
        .scalar_subquery()
    )
    await conn.execute(
        update(ClassSession)
        .where(
            ClassSession.id == session_id,
            ClassSession.attendance_taken_at.is_(None),
            ClassSession.deleted_at.is_(None),
            marked >= expected,
        )
        .values(attendance_taken_at=func.now(), attendance_taken_by_id=teacher_id)
    )


# ── voice notes ─────────────────────────────────────────────────────────


async def create_voice_note(
    conn: AsyncConnection,
    session_id: UUID,
    student_id: UUID,
    class_id: UUID,
    teacher_id: UUID,
    duration_ms: int,
    audio: bytes,
    mime_type: str | None,
    byte_size: int | None,
) -> UUID:
    return await scalar(
        conn,
        pg_insert(VoiceNote)
        .values(
            session_id=session_id,
            student_id=student_id,
            class_id=class_id,
            teacher_id=teacher_id,
            duration_ms=duration_ms,
            audio=audio,
            mime_type=mime_type,
            byte_size=byte_size,
            transcription_status="pending",
        )
        .returning(VoiceNote.id),
    )


async def get_voice_note_file(conn: AsyncConnection, voice_note_id: UUID) -> dict[str, Any]:
    """{audio, storage_key, mime_type}."""
    row = await fetch_required(
        conn,
        select(VoiceNote.audio, VoiceNote.storage_key, VoiceNote.mime_type).where(
            VoiceNote.id == voice_note_id, VoiceNote.deleted_at.is_(None)
        ),
    )
    return dict(row)


async def voice_note_exists(conn: AsyncConnection, voice_note_id: UUID) -> None:
    found = await scalar(
        conn,
        select(
            select(1).where(VoiceNote.id == voice_note_id, VoiceNote.deleted_at.is_(None)).exists()
        ),
    )
    if not found:
        raise NotFound


async def _one_row_or_not_found(conn: AsyncConnection, stmt: Executable) -> None:
    result = await conn.execute(stmt)
    if result.rowcount == 0:
        raise NotFound


def _live_voice_note(voice_note_id: UUID):
    return update(VoiceNote).where(VoiceNote.id == voice_note_id, VoiceNote.deleted_at.is_(None))


async def delete_voice_note(conn: AsyncConnection, voice_note_id: UUID) -> None:
    await _one_row_or_not_found(conn, _live_voice_note(voice_note_id).values(deleted_at=func.now()))


async def set_voice_note_transcript(
    conn: AsyncConnection, voice_note_id: UUID, transcript: str
) -> None:
    await _one_row_or_not_found(
        conn,
        _live_voice_note(voice_note_id).values(
            transcript=transcript, transcription_status="completed"
        ),
    )


async def mark_voice_note_transcription_failed(conn: AsyncConnection, voice_note_id: UUID) -> None:
    await _one_row_or_not_found(
        conn, _live_voice_note(voice_note_id).values(transcription_status="failed")
    )


# ── notifications ───────────────────────────────────────────────────────


async def list_notifications(
    conn: AsyncConnection, teacher_id: UUID, kind: str, limit: int, before: datetime | None
) -> list[dict[str, Any]] | None:
    n = Notification
    filters = []
    if kind:
        filters.append(n.kind == kind)
    if before is not None:
        filters.append(n.created_at < before)
    rows = await fetch_all(
        conn,
        select(
            n.id,
            n.kind,
            n.category,
            n.severity,
            n.title,
            n.body,
            n.created_at,
            n.read_at,
            n.dismissed_at,
            case(
                (
                    Student.id.is_not(None),
                    func.coalesce(Student.preferred_name, Student.given_name)
                    + " "
                    + Student.paternal_surname,
                )
            ).label("student_name"),
            Class.name.label("class_name"),
        )
        .outerjoin(Student, Student.id == n.student_id)
        .outerjoin(Class, Class.id == n.class_id)
        .where(n.recipient_teacher_id == teacher_id, n.deleted_at.is_(None), *filters)
        .order_by(n.created_at.desc())
        .limit(limit),
    )
    return [dict(r) for r in rows] or None


async def mark_notification_read(
    conn: AsyncConnection, notification_id: UUID, teacher_id: UUID
) -> None:
    await _one_row_or_not_found(
        conn,
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.recipient_teacher_id == teacher_id,
            Notification.deleted_at.is_(None),
        )
        .values(read_at=func.coalesce(Notification.read_at, func.now())),
    )


async def mark_all_notifications_read(conn: AsyncConnection, teacher_id: UUID) -> int:
    result = await conn.execute(
        update(Notification)
        .where(
            Notification.recipient_teacher_id == teacher_id,
            Notification.read_at.is_(None),
            Notification.deleted_at.is_(None),
        )
        .values(read_at=func.now())
    )
    return result.rowcount
