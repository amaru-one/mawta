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

## Change Log
- 2026-09-04: `recomputeOne`'s assessment query gained `and a.value_scale = 'numeric'` (`migrations/00008`). Only a numeric piece has anything a weighted average can use: a letter is not a small number — converting one into the average is exactly the arithmetic RVM 094-2020 refuses — and an unvalued piece has no value at all. The API already forces `counts_toward_internal` off for both, so this is the same rule restated where it is relied on, and it is also what keeps the not-null scan of `s.max_value` safe now that the column is nullable.
- 2026-08-28: `recomputeOne`'s assessment query now filters `a.counts_toward_internal` (`migrations/00005`), so evidence a teacher files out of the school's average stops moving it. Verified against the seed tenant: a 20/20 on an excluded assessment leaves the computed grade where it was, and the same mark on an ordinary one moves it. Nothing else changed — the criterio path never passes through this package.
- 2026-08-27: Deleted `termrisk.go` and `promotion.go`, and gutted `common.go` back to its package doc — the whole predictive subsystem was cut (see `migrations/SPEC.md` `00003`). `recomputeOne`'s return value is no longer consumed: `GradeRecompute` chained `risk.term_failure` off it, and there is nothing left to chain. `internal/promotion`, which `promotion.go` delegated every rule to, was deleted with it.
- 2026-08-26: Added `promotion.go` and re-anchored `termrisk.go` off `passing_value` onto the lowest band's ceiling. Moved `riskRule`, `loadRiskRule`, `upsertRiskFlag` and `resolveFlagIfActive` into `common.go` so both handlers share them; `upsertRiskFlag` now takes severity separately (a projected PER outranks a projected RR) and both helpers take a nullable class id, since a promotion projection is about a student's whole year and carries no class.
- 2026-08-25: Deleted `risk.go`, `sweep.go`, `summary.go`, `retention.go`; added `termrisk.go`. `common.go` lost `tenantToday` (its only caller was `risk.go`). `recomputeOne` now returns `(bool, error)` so recompute can chain the risk job only when grades actually changed.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
