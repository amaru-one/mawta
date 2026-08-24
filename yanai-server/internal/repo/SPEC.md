## Purpose
All hand-written SQL behind the HTTP handlers and job enqueueing: one file per screen/domain area, each function taking a `pgx.Tx` already carrying tenant context.

## Contents
- `home.go` — `TenantToday`, `GetHome`, `SearchClasses`. `me.go` — `GetMe`. `profile.go` — `GetProfile`.
- `classes.go` — `GetClassInfo`, `GetClassDashboard` (incl. per-component grade-registration progress), `ListSessions`.
- `sessions.go` — `GetSessionHeader`, `GetSessionRoster`. `roster.go` — `RosterAsOf` (enrollment as of a date).
- `attendance.go` — `GetSessionMeta`, `UpsertAttendance`, `MarkAllPresent`, `MaybeStampAttendanceTaken`.
- `observations.go` — `UpsertObservation` (participation, note, flag types). `flagtypes.go` — `ListFlagTypes`.
- `grades.go` — `GetStudentGrades`, `GetEffectiveScheme`, `GetComponentIDByCode`, `CreateAssessment`, `CreateScore`, `CorrectScore` (supersedes the old score row; correcting twice concurrently 409s).
- `practice_scores.go` — create/delete/list unofficial practice scores.
- `voicenotes.go` — `CreateVoiceNote` (audio bytes in DB), `GetVoiceNoteFile`, `SetVoiceNoteTranscript`, `SetVoiceNoteStatus`.
- `notifications.go` — list (cursor on created_at), unread count, mark read/read-all, dismiss.
- `terms.go` — `ResolveTerm` (explicit id or current term).
- `events.go` — `LogEvent`, `LogJobEvent`, `LogStudentReads` (mandatory for reads returning identifiable students).
- `jobs.go` — `EnqueueJob` (queue hardcoded 'default'; dedupes on `(kind, unique_key)` while available/retryable/scheduled/running).

## Inputs / Outputs
Inputs: `pgx.Tx` from `db.WithTenantTx` (or worker transactions) — RLS scopes every query. Outputs: response structs serialized by `httpapi`, plus rows in `jobs` and `events`.

## Conventions & Constraints
- Functions never open transactions; they run inside the caller's.
- Tenant id on inserts comes from `app.current_tenant_id()`, never a Go parameter (except `EnqueueJob`, whose tenant_id column is outside RLS).
- Scores and computed grades are append-only: corrections insert + stamp `superseded_at`; no in-place updates.
- Soft deletes (`deleted_at`) everywhere; filter them in every query.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
