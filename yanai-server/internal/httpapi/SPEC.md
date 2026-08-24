## Purpose
The chi router, middleware, and HTTP handlers — one handler file per screen of `yanai-views.html`. Handlers parse/validate, open a tenant transaction, call `repo`, enqueue jobs, and log events; SQL lives in `repo`.

## Contents
- `router.go` — `API` struct, `New`, `Router()` (all routes under `/api/v1` behind `tenantAuth`; `/healthz` outside), `handleHealthz`.
- `middleware.go` — `requestID`, `requestLogger`, `tenantAuth` (validates `X-Tenant-ID`/`X-Actor-ID`, resolves the teacher, builds `db.TenantCtx`), `tenantCtxFrom`.
- `home.go` — GET /home, GET /classes (search), date resolution in tenant timezone.
- `common.go` — GET /me.
- `class.go` — GET class dashboard, GET class sessions, POST session start/complete.
- `session.go` — GET session roster, PUT attendance (absent enqueues `risk.detect`), POST mark-all-present (enqueues class-wide `risk.detect`), PUT observation, voice-note create/audio/transcript/save/discard.
- `grades.go` — GET student grades, POST assessment, POST score create/correct (both enqueue `grade.recompute`), POST summary request (enqueues `note_summary.generate`), `enqueueGradeRecompute` helper.
- `practice_scores.go` — POST create / POST delete unofficial practice scores.
- `notifications.go` — list, unread-count, mark read, read-all, dismiss.
- `profile.go` — GET /profile. `flag_types.go` — GET /flag-types.
- `params.go` — path/query parsing helpers and error shorthand. `respond.go` — `writeJSON`/`writeError`/`writeAppError`.

## Inputs / Outputs
Inputs: HTTP requests with dev-auth headers. Outputs: JSON responses (snake_case, RFC3339 timestamps, empty lists as null); rows via `repo`; jobs via `repo.EnqueueJob` in the same transaction as the triggering write; audit events via `repo.LogEvent`/`LogStudentReads`.

## Conventions & Constraints
- One tenant transaction per request via `a.db.WithTenantTx`; enqueue + event-log inside it so they're atomic with the write.
- Every response returning identifiable student rows must log `student.read` events (`repo.LogStudentReads`).
- Route changes cascade to `bruno/yanai-api.yaml` and the UI's `src/lib/api/endpoints/`.
- Handlers contain no SQL — queries belong in `internal/repo`.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
