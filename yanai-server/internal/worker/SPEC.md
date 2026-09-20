## Purpose
The in-process background job processor: a `SELECT ... FOR UPDATE SKIP LOCKED` claim loop over the `jobs` table, a handler registry keyed by job kind, and exponential-backoff retries. Two kinds today: `grade.recompute` (the school's optional internal weighted grade) and `voice_note.transcribe` (Spanish speech-to-text via OpenAI). Nothing here touches the official record — the nivel de logro per competencia is asserted by a teacher through the HTTP API (RVM 094-2020).

## Contents
- `worker.go` — `Run` (spawns `WORKER_CONCURRENCY` poll loops), `Job`, `HandlerFunc`, claim/dispatch/success/failure bookkeeping (backoff `min(attempts^4, 3600)`s, error records appended to `jobs.errors`).
- `registry.go` — `defaultRegistry(cfg config.Config)`: the only place a job kind is wired to its handler; adapts `handlers` plain-argument functions to `HandlerFunc`. Also the one place a handler's external dependencies (today: `internal/stt.Client`, built from `cfg`) are constructed — once, at registry-assembly time, not per job.
- `handlers/` — one file per job kind (see its SPEC.md).
- `worker_db_test.go` — needs a database (`internal/dbtest`; skips without one). Exercises the `jobs` table directly rather than `Run`, which loops forever and builds its own registry: claim eligibility, that a `running` job is not claimable twice, the abandoned-job behaviour and the dedup-key consequence below, that another queue is never polled, and that `tenant_id` is nullable on purpose.


## Inputs / Outputs
Inputs: rows in `jobs` (enqueued by `repo.EnqueueJob` — from `httpapi` score writes for `grade.recompute`, from voice-note creation for `voice_note.transcribe`). Outputs: `computed_grades` + `computed_grade_components` for the former; `voice_notes.transcript`/`.transcription_status` for the latter; job rows finalized as completed/retryable/discarded either way.

## Conventions & Constraints
- Tenant jobs run in `db.WithTenantTx` (RLS, actor_type 'job'); nil-tenant jobs in `WithSystemTx`. Handlers must be idempotent and use `app.current_tenant_id()` for inserts.
- `handlers` must not import `worker` (import cycle) — handlers take plain args (`jobID int64`, `payload []byte`). A handler needing an external dependency (an HTTP client, a config value) takes it as a constructor argument and returns a closure with the same plain-argument shape — see `handlers.VoiceNoteTranscribe` and its wiring in `registry.go`. The dependency is built once when the registry is assembled, never inside the closure.
- `repo.EnqueueJob` hardcodes queue 'default'; changing `WORKER_QUEUE` alone means nothing is claimed.
- **There is no ticker and no scheduler.** All work is event-driven off a teacher action (saving a score, recording a voice note). Nothing runs periodically; nothing scans tenants.
- Rules live in a pure package (`internal/grading`); handlers are I/O only.
- **No job may write or suggest a nivel de logro.** Asserting one is a teacher's act, and the worker has no path to `competency_term_levels`.
- No lease reaper: a job whose worker dies stays `running`; diagnose via `attempted_by`/`attempted_at`.
- **An abandoned `running` job poisons its dedup key permanently, and that is worse than losing one job.** `jobs_unique_key_idx` includes `'running'` in its predicate, so while a job is running `repo.EnqueueJob` for the same `(kind, unique_key)` is a silent `do nothing`. With no reaper, a worker that dies mid-job leaves the key blocked forever: every later `grade.recompute` for that student/class/term is dropped and the student's internal grade stops updating, with nothing in the logs to say so. The symptom is silence, not an error. `worker_db_test.go` demonstrates it, and asserts the contrast — a `completed` job releases its key normally. Recorded rather than fixed by decision; fix it before anything depends on recovery. A reaper, or dropping `'running'` from the index predicate, are the two obvious directions, and either one changes those tests deliberately.
- **A handler returns `nil` for "processed, nothing more to do", not just for "succeeded."** `voice_note.transcribe` returns `nil` (job `completed`) on a permanent transcription failure (bad audio, no API key) after recording that outcome in the domain row (`transcription_status = 'failed'`) — returning an error there would burn up to 20 retries, each a real (possibly billable) call to a provider, against something retrying can never fix. An error is reserved for conditions retrying might actually resolve (network blip, rate limit, 5xx).

## Open Questions
- None.
