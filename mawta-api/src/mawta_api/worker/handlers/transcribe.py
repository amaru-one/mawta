"""voice_note.transcribe.

The only kind here besides agent.generate. The official record, the nivel de logro per
competencia under RVM 094-2020, is asserted by a teacher through the HTTP API and is never
produced by a job.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from psycopg import AsyncConnection

from mawta_api import applog
from mawta_api.errors import NotFound
from mawta_api.repo import sessions as repo
from mawta_api.stt import SttPermanentError


class Transcriber(Protocol):
    async def transcribe(self, audio_mp3: bytes) -> str: ...


# Runs in the job's transaction once a transcript is saved (the registry queues the redaction
# sweep of the note with it).
AfterTranscript = Callable[[AsyncConnection, UUID], Awaitable[None]]


def voice_note_transcribe(
    transcriber: Transcriber, *after: AfterTranscript
) -> Callable[[AsyncConnection, int, dict], Awaitable[None]]:
    """A handler bound to one Transcriber, built once when the registry is assembled."""

    async def handle(conn: AsyncConnection, job_id: int, payload: dict) -> None:
        try:
            voice_note_id = UUID(str(payload["voice_note_id"]))
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid voice_note.transcribe payload") from exc
        try:
            file = await repo.get_voice_note_file(conn, voice_note_id)
        except NotFound:
            # Discarded (soft-deleted) before the job ran. Nothing to do, so the attempt is
            # reported as skipped. No provider call happened, so no usage event was emitted.
            applog.report_outcome(applog.OUTCOME_SKIPPED, "voice_note_discarded")
            return
        if file["audio"] is None:
            # Legacy note: audio only ever reached storage_key on disk, from before audio moved
            # into this table. Not worth reading STORAGE_DIR from the worker for a handful of
            # historical rows.
            await repo.mark_voice_note_transcription_failed(conn, voice_note_id)
            return
        try:
            text = await transcriber.transcribe(bytes(file["audio"]))
        except SttPermanentError:
            # The provider call happened and its usage event was already logged inside
            # transcribe, so recording the failure here cannot hide the spend. The job completes
            # (the failure is recorded on the voice note), but the attempt is reported as a
            # permanent failure, never as a successful transcription.
            applog.report_outcome(applog.OUTCOME_PERMANENT_FAILURE, "transcription_failed")
            await repo.mark_voice_note_transcription_failed(conn, voice_note_id)
            return
        # any other error is transient: let the worker's normal backoff retry
        await repo.set_voice_note_transcript(conn, voice_note_id, text)
        for hook in after:
            await hook(conn, voice_note_id)

    return handle
