## Purpose
Per-kind job handlers dispatched by `internal/worker`'s registry. Each runs inside one already-open transaction (tenant RLS context set by the dispatcher).

There is exactly one kind. The official record — the nivel de logro per competencia under RVM 094-2020 — is asserted by a teacher through the HTTP API and is never produced by a job.

## Contents
- `common.go` — package doc only (the no-import-of-worker rule and the note above). Held the shared risk plumbing until `00003` removed the predictive subsystem.
- `recompute.go` — `GradeRecompute` (`grade.recompute`): recomputes the live `term_partial` computed grade for one student or all students with live scores in a class/term. Loads scheme/policy/weights/attempts, calls `internal/grading.Compute`, skips when the `inputs_digest` (sha256 of scheme version + sorted live score ids) is unchanged, supersedes the old row, inserts `computed_grades` + `computed_grade_components`, derives trend vs. the prior row. Feeds the school's optional internal weighted system only — never the official record. Chains nothing.

## Inputs / Outputs
Inputs: `pgx.Tx` + job id + raw JSON payload from the registry adapter. Outputs: rows in `computed_grades` (+ components). No chained jobs.

## Conventions & Constraints
- Never import `worker` (import cycle). Signature: `func X(ctx, tx pgx.Tx, [jobID int64,] payload []byte) error`.
- Idempotent; one transaction — an error rolls back everything the handler wrote.
- **Nothing here reads `grade_scales.passing_value` or `grade_scale_levels.is_passing`.** Both encoded "nota 11 aprobatoria", which applied to Secundaria for the 2020 school year only (Anexo 07 of RVM 094-2020, ended by transitoria 8.3).
- **No handler may write, suggest or imply a nivel de logro.** `competency_term_levels` is written only by a teacher's explicit action in `internal/repo/competencies.go`. A job that derived one would put a computation back where the norm puts a judgement.
- **`assessments.counts_toward_internal` is filtered here and nowhere else.** It is a property of the school's own average, not of the evidence: a piece of evidence excluded from the number still carries criterio levels that feed the teacher's judgement of the competencia, which is the official record. A query anywhere else that filtered on this column would be dropping evidence from the norm's side of the app.
- Known gotcha (full detail in `../CLAUDE.md`): the grade digest ignores in-place scheme edits.

## Open Questions
- None.
