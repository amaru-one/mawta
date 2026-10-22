"""Class sessions, attendance, voice notes, notifications."""

from datetime import date, datetime
from typing import Any, LiteralString
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.abc import Params
from psycopg.rows import DictRow

from db import fetch_all, fetch_one, fetch_required
from errors import NotFound
from repo.roster import roster_as_of


async def get_session_header(conn: AsyncConnection[DictRow], session_id: UUID) -> dict[str, Any]:
    h = await fetch_required(
        conn,
        """
        select cs.id as session_id, cs.class_id, c.name as class_name, cs.term_id, cs.topic,
               cs.session_date, cs.status
          from class_sessions cs
          join classes c on c.id = cs.class_id
         where cs.id = %s and cs.deleted_at is null
        """,
        (session_id,),
    )
    roster = await roster_as_of(conn, h["class_id"], h["session_date"])
    marked = await fetch_required(
        conn,
        "select count(*) as n from attendance_records where session_id = %s and deleted_at is null",
        (session_id,),
    )
    return {
        "session_id": h["session_id"],
        "class_id": h["class_id"],
        "class_name": h["class_name"],
        "term_id": h["term_id"],
        "topic": h["topic"],
        "session_date": h["session_date"].isoformat(),
        "status": h["status"],
        "attendance_marked": marked["n"],
        "attendance_total": len(roster),
    }


async def get_session_roster(
    conn: AsyncConnection[DictRow], session_id: UUID, class_id: UUID, session_date: date, q: str
) -> tuple[list[dict[str, Any]] | None, list[UUID]]:
    """The roster-as-of-session_date for a lesson screen, optionally filtered by a name
    substring. Returns the roster (None when empty: the UI expects null) and the ordered
    student ids, so the caller can log student.read events in the same transaction."""
    rows = await fetch_all(
        conn,
        """
        select st.id as student_id,
               coalesce(st.preferred_name, st.given_name) || ' ' || st.paternal_surname as name,
               ar.status as attendance_status
          from section_memberships sm
          join classes c on c.section_id = sm.section_id and c.id = %(class)s
          join students st on st.id = sm.student_id and st.deleted_at is null
          left join attendance_records ar
                 on ar.session_id = %(session)s and ar.student_id = st.id and ar.deleted_at is null
         where sm.joined_on <= %(d)s and (sm.left_on is null or sm.left_on > %(d)s)
           and sm.deleted_at is null
           and (%(q)s::text = '' or (coalesce(st.given_name,'') || ' ' ||
                coalesce(st.paternal_surname,'') || ' ' || coalesce(st.maternal_surname,''))
                ilike '%%' || %(q)s::text || '%%')
         order by st.paternal_surname, st.given_name
        """,
        {"class": class_id, "session": session_id, "d": session_date, "q": q},
    )
    notes = await fetch_all(
        conn,
        """
        select student_id, id, duration_ms, transcript
          from voice_notes
         where session_id = %s and deleted_at is null
         order by recorded_at
        """,
        (session_id,),
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


async def get_session_meta(conn: AsyncConnection[DictRow], session_id: UUID) -> tuple[UUID, date]:
    """The class and calendar date of a session: the minimum needed to compute its roster."""
    row = await fetch_required(
        conn,
        "select class_id, session_date from class_sessions where id = %s and deleted_at is null",
        (session_id,),
    )
    return row["class_id"], row["session_date"]


async def upsert_attendance(
    conn: AsyncConnection[DictRow],
    session_id: UUID,
    student_id: UUID,
    teacher_id: UUID,
    status: str,
    minutes_late: int | None,
    note: str | None,
) -> None:
    """Denormalized columns (class_id, session_date) are filled by the sync_denormalised trigger."""
    await conn.execute(
        """
        insert into attendance_records (tenant_id, session_id, student_id, status, minutes_late,
                                        note, source, recorded_by_id)
        values (app.current_tenant_id(), %(session)s, %(student)s, %(status)s,
                %(late)s::smallint, %(note)s, 'manual', %(teacher)s)
        on conflict (session_id, student_id) where deleted_at is null
        do update set status = excluded.status, minutes_late = excluded.minutes_late,
                      note = excluded.note, source = 'manual',
                      recorded_by_id = excluded.recorded_by_id, recorded_at = now()
        """,
        {
            "session": session_id,
            "student": student_id,
            "status": status,
            "late": minutes_late,
            "note": note,
            "teacher": teacher_id,
        },
    )


async def mark_all_present(
    conn: AsyncConnection[DictRow],
    session_id: UUID,
    class_id: UUID,
    teacher_id: UUID,
    session_date: date,
) -> int:
    """A 'present' row for every roster student with no attendance row yet, without clobbering
    explicit marks already taken."""
    cur = await conn.execute(
        """
        insert into attendance_records (tenant_id, session_id, student_id, status, source,
                                        recorded_by_id)
        select app.current_tenant_id(), %(session)s, sm.student_id, 'present', 'bulk', %(teacher)s
          from section_memberships sm
          join classes c on c.section_id = sm.section_id
         where c.id = %(class)s
           and sm.joined_on <= %(d)s and (sm.left_on is null or sm.left_on > %(d)s)
           and sm.deleted_at is null
        on conflict (session_id, student_id) where deleted_at is null do nothing
        """,
        {"session": session_id, "teacher": teacher_id, "class": class_id, "d": session_date},
    )
    return cur.rowcount


async def maybe_stamp_attendance_taken(
    conn: AsyncConnection[DictRow], session_id: UUID, teacher_id: UUID
) -> None:
    """Set attendance_taken_at/_by once every roster student as of the session date has a row."""
    await conn.execute(
        """
        update class_sessions cs
           set attendance_taken_at = now(), attendance_taken_by_id = %(teacher)s
         where cs.id = %(session)s
           and cs.attendance_taken_at is null
           and cs.deleted_at is null
           and (select count(*) from attendance_records ar
                 where ar.session_id = cs.id and ar.deleted_at is null)
               >= (select count(*) from section_memberships sm
                     join classes c on c.section_id = sm.section_id
                    where c.id = cs.class_id
                      and sm.joined_on <= cs.session_date
                      and (sm.left_on is null or sm.left_on > cs.session_date)
                      and sm.deleted_at is null)
        """,
        {"session": session_id, "teacher": teacher_id},
    )


# ── voice notes ─────────────────────────────────────────────────────────


async def create_voice_note(
    conn: AsyncConnection[DictRow],
    session_id: UUID,
    student_id: UUID,
    class_id: UUID,
    teacher_id: UUID,
    duration_ms: int,
    audio: bytes,
    mime_type: str | None,
    byte_size: int | None,
) -> UUID:
    row = await fetch_required(
        conn,
        """
        insert into voice_notes (tenant_id, session_id, student_id, class_id, teacher_id,
                                  duration_ms, audio, mime_type, byte_size,
                                  transcription_status)
        values (app.current_tenant_id(), %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
        returning id
        """,
        (session_id, student_id, class_id, teacher_id, duration_ms, audio, mime_type, byte_size),
    )
    return row["id"]


async def get_voice_note_file(
    conn: AsyncConnection[DictRow], voice_note_id: UUID
) -> dict[str, Any]:
    """{audio, storage_key, mime_type}."""
    return await fetch_required(
        conn,
        "select audio, storage_key, mime_type from voice_notes where id = %s and deleted_at is null",
        (voice_note_id,),
    )


async def voice_note_exists(conn: AsyncConnection[DictRow], voice_note_id: UUID) -> None:
    row = await fetch_required(
        conn,
        "select exists (select 1 from voice_notes where id = %s and deleted_at is null) as ok",
        (voice_note_id,),
    )
    if not row["ok"]:
        raise NotFound


async def _one_row_or_not_found(
    conn: AsyncConnection[DictRow], sql: LiteralString, params: Params
) -> None:
    cur = await conn.execute(sql, params)
    if cur.rowcount == 0:
        raise NotFound


async def delete_voice_note(conn: AsyncConnection[DictRow], voice_note_id: UUID) -> None:
    await _one_row_or_not_found(
        conn,
        "update voice_notes set deleted_at = now() where id = %s and deleted_at is null",
        (voice_note_id,),
    )


async def set_voice_note_transcript(
    conn: AsyncConnection[DictRow], voice_note_id: UUID, transcript: str
) -> None:
    await _one_row_or_not_found(
        conn,
        """
        update voice_notes set transcript = %s, transcription_status = 'completed'
         where id = %s and deleted_at is null
        """,
        (transcript, voice_note_id),
    )


async def mark_voice_note_transcription_failed(
    conn: AsyncConnection[DictRow], voice_note_id: UUID
) -> None:
    await _one_row_or_not_found(
        conn,
        """
        update voice_notes set transcription_status = 'failed'
         where id = %s and deleted_at is null
        """,
        (voice_note_id,),
    )


# ── notifications ───────────────────────────────────────────────────────


async def list_notifications(
    conn: AsyncConnection[DictRow], teacher_id: UUID, kind: str, limit: int, before: datetime | None
) -> list[dict[str, Any]] | None:
    rows = await fetch_all(
        conn,
        """
        select n.id, n.kind, n.category, n.severity, n.title, n.body, n.created_at, n.read_at,
               n.dismissed_at,
               case when s.id is not null
                    then coalesce(s.preferred_name, s.given_name) || ' ' || s.paternal_surname
               end as student_name,
               c.name as class_name
          from notifications n
          left join students s on s.id = n.student_id
          left join classes c on c.id = n.class_id
         where n.recipient_teacher_id = %(teacher)s and n.deleted_at is null
           and (%(kind)s::text = '' or n.kind = %(kind)s::text)
           and (%(before)s::timestamptz is null or n.created_at < %(before)s::timestamptz)
         order by n.created_at desc
         limit %(limit)s
        """,
        {"teacher": teacher_id, "kind": kind, "before": before, "limit": limit},
    )
    return rows or None


async def mark_notification_read(
    conn: AsyncConnection[DictRow], notification_id: UUID, teacher_id: UUID
) -> None:
    await _one_row_or_not_found(
        conn,
        """
        update notifications set read_at = coalesce(read_at, now())
         where id = %s and recipient_teacher_id = %s and deleted_at is null
        """,
        (notification_id, teacher_id),
    )


async def mark_all_notifications_read(conn: AsyncConnection[DictRow], teacher_id: UUID) -> int:
    cur = await conn.execute(
        """
        update notifications set read_at = now()
         where recipient_teacher_id = %s and read_at is null and deleted_at is null
        """,
        (teacher_id,),
    )
    return cur.rowcount


_ = fetch_one
