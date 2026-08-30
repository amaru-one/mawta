## Purpose
Normalizes browser-recorded audio into one canonical format before storage.

## Contents
- `transcode.go` — `CanonicalMimeType = "audio/mpeg"` and `TranscodeToMP3(ctx, input)` which shells out to ffmpeg to convert arbitrary browser audio (webm/ogg/etc.) to MP3.

## Inputs / Outputs
Input: raw uploaded audio bytes from `httpapi/session.go` (voice-note creation). Output: MP3 bytes stored directly in `voice_notes.audio` (in-database, not object storage).

## Conventions & Constraints
- Requires `ffmpeg` on PATH (present in the production image).
- Everything stored downstream assumes `audio/mpeg`; don't bypass this on upload.

## Change Log
- 2026-08-29: Dropped the reference to migration `00015`, which no longer exists after the 2026-08-26 squash into `00001_initial_schema.sql`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
