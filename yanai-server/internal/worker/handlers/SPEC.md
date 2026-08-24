## Purpose
Per-kind job handlers dispatched by `internal/worker`'s registry. Each runs inside one already-open transaction (tenant RLS context set by the dispatcher).

## Contents
- `common.go` — package doc (no-import-of-worker rule) and `tenantToday` (today in the tenant's timezone).
- `recompute.go` — `GradeRecompute` (`grade.recompute`): recomputes the live `term_partial` computed grade for one student or all students with live scores in a class/term. Loads scheme/policy/weights/attempts, calls `internal/grading.Compute`, skips when the `inputs_digest` (sha256 of scheme version + sorted live score ids) is unchanged, supersedes the old row, inserts `computed_grades` + `computed_grade_components`, derives trend vs. the prior row.
- `risk.go` — `RiskDetect` (`risk.detect`): evaluates active `risk_rules` (codes `consecutive_absences`, `level_drop`) for one student or the roster; `upsertRiskFlag` (ON CONFLICT mirrors the `risk_flags_open_key` partial index exactly), evidence + titular-teacher alert notification only on fresh insert; `resolveFlagIfActive` closes flags whose condition no longer holds. No titular teacher → whole handler no-ops.
- `sweep.go` — `NotificationSweep` (`notification.sweep`): pure-SQL reminders, deduped on `(recipient_teacher_id, dedupe_key)` — `attendance_unmarked` (last 7 days, expires in 7 days) and `grades_pending` (published past-due assessments with missing live scores).
- `summary.go` — `NoteSummaryGenerate` (`note_summary.generate`): deterministic extractive stub (`model='extractive-stub-v1'`, no AI provider) — marks prior summaries stale, inserts a `generating` row, bullets = first sentence of up to 5 saved transcripts + a "sin transcribir" bullet, flips to `ready` (or `failed` when no notes), records `note_summary_sources`.
- `retention.go` — `RetentionSweep` (`retention.sweep`): non-destructive stub; counts students/voice notes past `retention_until` and logs a `retention.sweep_report` event. Deletes nothing.

## Inputs / Outputs
Inputs: `pgx.Tx` + job id + raw JSON payload from the registry adapter. Outputs: rows in computed_grades(+components), risk_flags(+evidence), notifications, note_summaries(+sources), events.

## Conventions & Constraints
- Never import `worker` (import cycle). Signature: `func X(ctx, tx pgx.Tx, [jobID int64,] payload []byte) error`.
- Idempotent; one transaction — an error rolls back everything the handler wrote.
- Known gotchas (full detail in `../CLAUDE.md`): grade digest ignores in-place scheme edits; `firstSentence` byte-truncates UTF-8; sweep queries use `current_date`, not `tenantToday`; changing the `risk_flags_open_key` index requires changing `upsertRiskFlag`'s ON CONFLICT clause.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
