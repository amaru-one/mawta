"""Class sessions, attendance, voice notes and their attribution."""

import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import Response

import authz
import domain
import media
from errors import AppError, bad_request, conflict, unprocessable
from repo import events as events_repo
from repo import jobs as jobs_repo
from repo import redaction as redaction_repo
from repo import sessions as repo
from web import (
    api_of,
    no_content,
    parse_date,
    parse_uuid,
    path_uuid,
    read_body,
    tc_of,
    write_json,
)

MAX_AUDIO_BYTES = 2 << 20  # 1 min at ~128 kbps is ~1 MB; 2x headroom
MIN_AUDIO_BYTES = 1000  # rejects near-empty/mis-tap blobs
MAX_DURATION_MS = 60_000  # voice notes are capped at 1 minute
INT32_MAX = 2**31 - 1


async def handle_session_start(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    session_id = path_uuid(request, "sessionID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_session_access(conn, tc, session_id)
        cur = await conn.execute(
            """
            update class_sessions
               set status = %s, actual_start_at = now(), started_by_id = %s
             where id = %s and status = %s and deleted_at is null
            """,
            (domain.SESSION_IN_PROGRESS, tc.teacher_id, session_id, domain.SESSION_SCHEDULED),
        )
        if cur.rowcount == 0:
            raise conflict("session cannot be started from its current state")
        await events_repo.log_event(
            conn, "session.started", "class_session", session_id, session_id=session_id
        )
    return write_json({"status": domain.SESSION_IN_PROGRESS})


async def handle_session_roster(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    session_id = path_uuid(request, "sessionID")
    q = request.query_params.get("q", "")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_session_access(conn, tc, session_id)
        header = await repo.get_session_header(conn, session_id)
        session_date = parse_date(header["session_date"])
        roster, student_ids = await repo.get_session_roster(
            conn, session_id, header["class_id"], session_date, q
        )
        assert tc.teacher_id is not None
        await events_repo.log_student_reads(
            conn, student_ids, tc.teacher_id, header["class_id"], session_id
        )
    return write_json({"header": header, "roster": roster})


async def handle_attendance_upsert(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    session_id = path_uuid(request, "sessionID")
    student_id = path_uuid(request, "studentID")
    req = await read_body(request, {"status": str, "minutes_late": int | None, "note": str | None})
    if req["minutes_late"] is not None and not -(2**15) <= req["minutes_late"] < 2**15:
        raise bad_request("invalid JSON body")
    async with api.db.tenant_tx(tc) as conn:
        guard_class_id = await authz.require_session_access(conn, tc, session_id)
        await authz.require_student_on_roster(conn, tc, guard_class_id, student_id)
        assert tc.teacher_id is not None
        await repo.upsert_attendance(
            conn,
            session_id,
            student_id,
            tc.teacher_id,
            req["status"],
            req["minutes_late"],
            req["note"],
        )
        await repo.maybe_stamp_attendance_taken(conn, session_id, tc.teacher_id)
        class_id, _ = await repo.get_session_meta(conn, session_id)
        await events_repo.log_event(
            conn,
            "attendance.marked",
            "attendance_record",
            None,
            {"status": req["status"]},
            student_id,
            class_id,
            session_id,
        )
    return write_json({"status": req["status"]})


async def handle_mark_all_present(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    session_id = path_uuid(request, "sessionID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_session_access(conn, tc, session_id)
        class_id, session_date = await repo.get_session_meta(conn, session_id)
        assert tc.teacher_id is not None
        marked = await repo.mark_all_present(
            conn, session_id, class_id, tc.teacher_id, session_date
        )
        await repo.maybe_stamp_attendance_taken(conn, session_id, tc.teacher_id)
        await events_repo.log_event(
            conn,
            "attendance.marked_bulk",
            "class_session",
            session_id,
            class_id=class_id,
            session_id=session_id,
        )
    return write_json({"marked": marked})


async def handle_create_voice_note(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    session_id = path_uuid(request, "sessionID")
    student_id = path_uuid(request, "studentID")

    duration_ms = 0
    audio = b""

    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        try:
            form = await request.form()
        except Exception:
            raise bad_request("invalid multipart form") from None
        raw_duration = form.get("duration_ms")
        if isinstance(raw_duration, str) and raw_duration:
            try:
                duration_ms = int(raw_duration)
            except ValueError:
                raise bad_request("invalid duration_ms") from None
            if not -INT32_MAX - 1 <= duration_ms <= INT32_MAX:
                raise bad_request("invalid duration_ms")
        upload = form.get("audio")
        if upload is not None and not isinstance(upload, str):
            audio = await upload.read(MAX_AUDIO_BYTES + 1)
            if len(audio) > MAX_AUDIO_BYTES:
                raise unprocessable("audio exceeds the 1-minute size limit")
    else:
        body = await read_body(request, {"duration_ms": int, "mime_type": str | None})
        duration_ms = body["duration_ms"]
        if not -INT32_MAX - 1 <= duration_ms <= INT32_MAX:
            raise bad_request("invalid JSON body")

    if duration_ms > MAX_DURATION_MS:
        raise unprocessable("voice notes cannot be longer than 1 minute")
    if len(audio) < MIN_AUDIO_BYTES:
        raise unprocessable("audio is missing or too short to be a valid recording")

    # Recording browsers disagree on codec/container (Chrome: WebM/Opus, Safari: MP4/AAC) and
    # neither can play the other's output, so every upload is normalized to one canonical
    # format before it's stored.
    try:
        audio = await media.transcode_to_mp3(audio)
    except media.TranscodeError:
        raise unprocessable("could not process audio") from None

    async with api.db.tenant_tx(tc) as conn:
        guard_class_id = await authz.require_session_access(conn, tc, session_id)
        await authz.require_student_on_roster(conn, tc, guard_class_id, student_id)
        class_id, _ = await repo.get_session_meta(conn, session_id)
        assert tc.teacher_id is not None
        voice_note_id = await repo.create_voice_note(
            conn,
            session_id,
            student_id,
            class_id,
            tc.teacher_id,
            duration_ms,
            audio,
            media.CANONICAL_MIME_TYPE,
            len(audio),
        )
        await jobs_repo.enqueue_job(
            conn,
            tc.tenant_id,
            domain.JOB_KIND_VOICE_NOTE_TRANSCRIBE,
            3,
            {"voice_note_id": str(voice_note_id)},
            f"voice_note.transcribe:{voice_note_id}",
        )
        await events_repo.log_event(
            conn,
            "voice_note.recorded",
            "voice_note",
            voice_note_id,
            student_id=student_id,
            class_id=class_id,
            session_id=session_id,
        )
    return write_json({"id": voice_note_id}, 201)


async def handle_voice_note_audio(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    voice_note_id = path_uuid(request, "voiceNoteID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_voice_note_access(conn, tc, voice_note_id)
        file = await repo.get_voice_note_file(conn, voice_note_id)

    media_type = file["mime_type"] or "application/octet-stream"
    if file["audio"] is not None:
        return Response(bytes(file["audio"]), media_type=media_type)

    # Legacy fallback: pre-migration recordings still on disk.
    if file["storage_key"] is None:
        raise AppError(404, "not_found", "audio not found")
    full_path = Path(api.settings.storage_dir) / file["storage_key"]
    try:
        data = full_path.read_bytes()
    except OSError:
        raise AppError(404, "not_found", "audio file not found") from None
    return Response(data, media_type=media_type)


async def handle_voice_note_save(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    voice_note_id = path_uuid(request, "voiceNoteID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_voice_note_access(conn, tc, voice_note_id)
        await repo.voice_note_exists(conn, voice_note_id)
        await events_repo.log_event(conn, "voice_note.saved", "voice_note", voice_note_id)
    return write_json({"status": "saved"})


async def handle_voice_note_discard(request: Request) -> Response:
    api, tc = api_of(request), tc_of(request)
    voice_note_id = path_uuid(request, "voiceNoteID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_voice_note_access(conn, tc, voice_note_id)
        await repo.delete_voice_note(conn, voice_note_id)
        await events_repo.log_event(conn, "voice_note.discarded", "voice_note", voice_note_id)
    return no_content()


# A voice note the name sweep discarded (it named only classmates, never its student) stays out
# of the descriptive conclusions without asking anyone. The teacher only sees it when it matters
# (when discarding it leaves too little evidence to propose a conclusion) and then decides: the
# note was recorded on the wrong student (reassign) or it does belong here (confirm).


async def handle_voice_note_reassign(request: Request) -> Response:
    """Move the note to another student of the same class and sweep it again around that
    student. Until the new sweep finishes the note is pending."""
    api, tc = api_of(request), tc_of(request)
    voice_note_id = path_uuid(request, "voiceNoteID")
    req = await read_body(request, {"student_id": str}, "invalid body")
    student_id = parse_uuid(req["student_id"], "invalid student_id")

    async with api.db.tenant_tx(tc) as conn:
        await authz.require_voice_note_access(conn, tc, voice_note_id)
        note = await redaction_repo.get_voice_note_for_redaction(conn, voice_note_id)
        await authz.require_student_on_roster(conn, tc, note["class_id"], student_id)
        if note["student_id"] == student_id:
            raise AppError(
                422,
                "same_student",
                "La nota ya está guardada en este estudiante. Usa «Sí es de este estudiante».",
            )
        await redaction_repo.reassign_voice_note(conn, voice_note_id, student_id)
        await events_repo.log_event(
            conn,
            "voice_note.reassigned",
            "voice_note",
            voice_note_id,
            {"from_student_id": str(note["student_id"])},
            student_id,
            note["class_id"],
        )
        out = {
            "id": voice_note_id,
            "student_id": student_id,
            "attribution_status": redaction_repo.ATTRIBUTION_PENDING,
        }
        if not api.settings.agent_ready("redaction"):
            return write_json(out)  # stays pending until the sweep has a model
        from agent import redaction as redaction_agent

        note["student_id"] = student_id
        assert tc.teacher_id is not None
        await redaction_agent.queue(conn, tc.tenant_id, note, tc.teacher_id, True)
    return write_json(out)


async def handle_voice_note_confirm(request: Request) -> Response:
    """The teacher says a discarded note does belong to its student. Only a note discarded for
    naming other students can be confirmed: an unreadable one has nothing to use."""
    api, tc = api_of(request), tc_of(request)
    voice_note_id = path_uuid(request, "voiceNoteID")
    async with api.db.tenant_tx(tc) as conn:
        await authz.require_voice_note_access(conn, tc, voice_note_id)
        note = await redaction_repo.get_voice_note_for_redaction(conn, voice_note_id)
        await redaction_repo.confirm_voice_note(conn, voice_note_id)
        await events_repo.log_event(
            conn,
            "voice_note.confirmed",
            "voice_note",
            voice_note_id,
            student_id=note["student_id"],
            class_id=note["class_id"],
        )
        out = {
            "id": voice_note_id,
            "student_id": note["student_id"],
            "attribution_status": redaction_repo.ATTRIBUTION_CONFIRMED,
        }
    return write_json(out)


_ = os
