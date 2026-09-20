## Purpose
Sends recorded voice-note audio to a speech-to-text provider and returns the Spanish
transcript. One provider (OpenAI), one function — no interface, no plugin surface.

## Contents
- `client.go` — `Client`, `NewClient(apiKey, model string) *Client`, `(*Client) Transcribe(ctx, audioMP3 []byte) (string, error)`, and `ErrPermanent`.

## Inputs / Outputs
Input: MP3 audio bytes — always MP3, since `media.TranscodeToMP3` (`internal/media`) is the only writer of `voice_notes.audio` and normalizes every upload to that format before it is ever stored. Output: the transcribed text, or an error. Consumed by `internal/worker/handlers.VoiceNoteTranscribe`, which is the only caller.

## Conventions & Constraints
- **No provider interface.** This package calls OpenAI's `POST /v1/audio/transcriptions` directly. This repo avoids abstractions with a single implementation (see `internal/media`, which shells out to ffmpeg directly rather than sitting behind a codec interface) — if a second provider is ever needed, that is when an interface earns its place, not before.
- **`ErrPermanent` is the only signal the caller needs.** `Transcribe` wraps `ErrPermanent` for anything retrying cannot fix — a missing API key, or a non-429 4xx from OpenAI (bad/empty audio, unsupported format). Every other error (network failure, 429, 5xx) is returned unwrapped, since those are exactly the cases the worker's own exponential backoff (`internal/worker/SPEC.md`) already handles correctly. The caller distinguishes with `errors.Is(err, stt.ErrPermanent)` — see `internal/worker/handlers/transcribe.go`.
- No API key hardcoded or required to construct a `Client`: `NewClient` accepts an empty key so the process can still boot without one configured (`internal/config/SPEC.md`); `Transcribe` itself returns a wrapped `ErrPermanent` on first use if the key is empty, rather than the package refusing to exist.
- `language=es` is always sent — this app has no non-Spanish deployment, and passing a fixed language avoids OpenAI's (slower, sometimes wrong) auto-detection.
- One `http.Client` per `Client` value, timeout 30s — generous for a clip that is capped at 60s of audio (`internal/httpapi/session.go`'s `maxDurationMs`), never reused across requests in a way that would need connection-pool tuning at this volume.
- No retry logic here — retries are the worker's job (backoff on the `jobs` row), not this package's. `Transcribe` makes exactly one HTTP call per invocation.

## Open Questions
- **The transcription success and transient-retry paths are untested, and cannot be tested as things stand.** `VoiceNoteTranscribe` takes a concrete `*stt.Client` whose endpoint is a package const, so no fake can be substituted and no `httptest.Server` can be pointed at. Only the permanent-failure branch is reachable offline — via an empty API key — and `internal/worker/handlers/handlers_db_test.go` covers that one. Keeping this package free of a provider interface was a deliberate decision; the cost of it is recorded here rather than left invisible. Narrowing the handler's parameter to a one-method interface would close the gap without changing this package's shape.
