## Purpose
All hand-written SQL behind the HTTP handlers and job enqueueing: one file per screen/domain area, each function taking a `pgx.Tx` already carrying tenant context.

## Contents
- `home.go` — `TenantToday`, `GetHome`, `SearchClasses`. `me.go` — `GetMe`. `profile.go` — `GetProfile`.
- `classes.go` — `GetClassInfo`, `GetClassDashboard` (incl. per-component grade-registration progress; `Distribution` counts *asserted* niveles de logro from `competency_term_levels`, not computed grades), `ListSessions`.
- `sessions.go` — `GetSessionHeader`, `GetSessionRoster`. `roster.go` — `RosterAsOf` (enrollment as of a date).
- `attendance.go` — `GetSessionMeta`, `UpsertAttendance`, `MarkAllPresent`, `MaybeStampAttendanceTaken`.
- `observations.go` — `UpsertObservation` (participation, note, flag types). `flagtypes.go` — `ListFlagTypes`.
- `grades.go` — `GetStudentGrades`, `GetEffectiveScheme`, `GetComponentIDByCode`, `CreateAssessment`, `CreateScore`, `CorrectScore` (supersedes the old score row; correcting twice concurrently 409s). `EvaluationEntry` carries no weight and each entry lists the criterios it evidences; `ComputedGradeView` is the optional internal weighted system and carries no projection.
- `competencies.go` — `ListClassCompetencyLevels` (levels + conclusion state, with the mandatory-conclusion classification), `AssertCompetencyLevel` and `UpsertConclusion` (both append-only with supersession), `conclusionRequirement`, `MissingMandatoryConclusions`.
- `criteria.go` — the criterios de evaluación layer: `ListClassCriteria` (every competencia of the class's área with its criterios, and optionally one student's level per criterio), `CreateCriterion` (rejects a blank description and a competencia outside the class's área), `DeleteCriterion` (soft), `AssertCriterionLevel` (append-only period-grain level, `assessment_id` null).
- `siagie.go` — `GetSiagieReport`: the end-of-period table per class, one row per student × competency, with `ready` false while mandatory conclusions are missing.
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

## Conventions & Constraints addendum
- A competency with no level for a period is reported as null, never as C: "no desarrollada" and "en inicio" are different facts (RVM 048-2024, 5.1.2.2 p.1).
- **Nothing derives a nivel de logro.** `AssertCompetencyLevel` leaves `suggested_level_id` and `computed_grade_id` null on purpose: under RVM 094-2020 the level is the teacher's judgement of the period's evidence against the criterios, and a computed number sitting beside it in the UI is exactly the framing the norm moves away from. Criterio levels are evidence and are never rolled up.
- `competency_term_levels.class_id` is provenance, not identity. Scope reads by the class's *área* and roster — `MissingMandatoryConclusions` does — so a level asserted from another class still blocks its own área and never blocks someone else's.

## Change Log
- 2026-08-27: Realigned the grade path with RVM 094-2020. Added `criteria.go`. `AssertCompetencyLevel` no longer reads `computed_grades` and stops writing `suggested_level_id`/`computed_grade_id`; `ListClassCompetencyLevels` no longer returns `suggested_level`. `GetStudentGrades` drops `weight` from each evaluation (they are evidence, not shares of a grade) and drops the projection columns from `ComputedGradeView`; it no longer inner-joins `grading_scheme_component_weights`, so an assessment shows as evidence whether or not its component is weighted, and it now attaches the criterios each assessment evidences via `assessment_criteria`. `GetClassDashboard` lost `Stats.EnRiesgo` and `AtRisk` (the risk tables are gone) and its `Distribution` now counts asserted levels rather than computed grades; it returns `(ClassDashboard, error)` instead of also returning at-risk student ids. Cascade: `yanai-ui/src/lib/api/dto.ts`, `internal/httpapi`.
- 2026-08-25: `GetStudentGrades` evaluations now carry `component_name` (`gc.name`) alongside `component_code`. The UI had been hardcoding a code→label map and title-casing unknown codes, which broke on multi-word competencia components; the class dashboard already used `gc.name`, so the two screens now agree. Cascade: `yanai-ui/src/lib/api/dto.ts`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
