## Purpose
Pure grade-computation math for `grade.recompute`: turns a student's attempts + component weights + scheme policy into a normalized term grade. No I/O.

## Contents
- `compute.go` — input types (`Attempt`, `AssessmentInput`, `ComponentWeight`, `Policy`), outputs (`ComponentResult`, `Result` incl. `BelowMinEvaluated`, projections, counted/dropped/excused score ids), `resolveAssessment` (per-assessment attempt resolution: retake policy, caps, absent handling), `Compute` (weighting, drop-lowest-N, aggregation, evaluated-weight ratio), and `Round` (rounding modes/decimals).

## Inputs / Outputs
Called only by `internal/worker/handlers/recompute.go`, which loads inputs from SQL and persists the `Result` into `computed_grades`.

## Conventions & Constraints
- Keep this package pure and deterministic — no SQL, no context/tx, no time.Now. All persistence stays in the worker handler.
- Policy semantics (rounding mode, absent_counts_as, retake_policy, min_evaluated_weight_for_grade) must match `grading_scheme_versions` column semantics in migration 00008.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
