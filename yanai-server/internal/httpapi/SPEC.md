## Purpose
The chi router, middleware, and HTTP handlers — one handler file per screen of `yanai-views.html`. Handlers parse/validate, open a tenant transaction, call `repo`, enqueue jobs, and log events; SQL lives in `repo`.

## Contents
- `router.go` — `API` struct, `New`, `Router()` (all routes under `/api/v1` behind `tenantAuth`; `/healthz` outside), `handleHealthz`.
- `middleware.go` — `requestID`, `requestLogger`, `tenantAuth` (validates `X-Tenant-ID`/`X-Actor-ID`, resolves the teacher, builds `db.TenantCtx`), `tenantCtxFrom`.
- `home.go` — GET /home, GET /classes (search), date resolution in tenant timezone.
- `common.go` — GET /me.
- `class.go` — GET class dashboard, GET class sessions, POST session start/complete.
- `session.go` — GET session roster, PUT attendance, POST mark-all-present, PUT observation, voice-note create/audio/transcript/save/discard. (Attendance no longer enqueues risk work — risk is grade-driven now.)
- `grades.go` — GET student grades, POST assessment, POST score create/correct (both enqueue `grade.recompute`, which chains nothing), POST summary request (**retired: returns 501**), `enqueueGradeRecompute` helper.
- `competencies.go` — the official MINEDU record: GET competencies for a student (level, whether a conclusión descriptiva is mandatory and why — there is deliberately no suggested level), POST competency-level (the only writer of an official nivel de logro), POST conclusion, GET siagie-report.
- `criteria.go` — the criterios de evaluación a competencia is judged against: GET class criteria (optionally with one student's level per criterio), POST criterion (the teacher writes their own), POST criterion delete, POST criterion-level (period-grain, evidence only).
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
- A nivel de logro is only ever written from an explicit teacher action. No handler may derive one from `computed_grades`; the suggestion travels as `suggested_level_id` so an override stays auditable (RVM 094-2020, 5.1.1.3 p.2-3).
- Whether a conclusión descriptiva is mandatory is derived server-side from the student's live level, never taken from the request body.

## Change Log
- 2026-08-27: Added `criteria.go` and its four routes, the surface where a teacher writes the criterios a competencia is judged against and records a level per criterio per periodo. Removed `enqueuePromotionProjection` from `competencies.go` (the job kind is gone) and rewrote the doc comments that described a "suggested level" — under RVM 094-2020 the level is a judgement of evidence against the criterios, not a number the system offers first. `class.go` stopped logging at-risk student reads, since the dashboard no longer returns an at-risk list. Cascade: `internal/repo`, `yanai-ui`.
- 2026-08-26: Added `competencies.go` and its four routes. This is the first surface that writes what RVM 094-2020 actually regulates — a nivel de logro per competencia per periodo — rather than the computed grade that had been standing in for it. `siagie-report` reports `ready: false` while any mandatory conclusion is missing, so a period cannot be sent incomplete.
- 2026-08-25: Removed both `risk.detect` enqueues from `session.go` (attendance marking no longer triggers risk). `handleRequestSummary` now returns 501 without enqueueing — the `note_summary.generate` handler is gone, and enqueueing an unhandled kind would burn 20 attempts before being discarded. The route and its UI caller are intentionally left in place so the button surfaces a clear error.

- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- `POST /classes/{classID}/students/{studentID}/summary` is a 501 stub. Either restore summary generation or remove the route together with the UI affordance in `yanai-ui/src/lib/api/endpoints/grades.ts` and the button that calls it.
