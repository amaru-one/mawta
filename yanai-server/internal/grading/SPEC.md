## Purpose
Pure grade-computation math for `grade.recompute`: turns a student's attempts + component weights + scheme policy into a normalized term grade. No I/O.

**This is the school's optional internal weighted system, never the official record.** RVM 094-2020 (mod. 048-2024) determines achievement per competencia from the teacher's judgement of evidence against the criterios de evaluación, with no weighted average anywhere; that record is `competency_term_levels` and nothing here feeds it. A private IE may run its own internal numeric system (D.S. 009-2006-ED art. 37.4.f) — that is what this computes.

## Contents
- `compute.go` — input types (`Attempt`, `AssessmentInput`, `ComponentWeight`, `Policy`), outputs (`ComponentResult`, `Result` incl. `BelowMinEvaluated`, counted/dropped/excused score ids), `resolveAssessment` (per-assessment attempt resolution: retake policy, caps, absent handling), `Compute` (weighting, drop-lowest-N, aggregation, evaluated-weight ratio), and `Round` (rounding modes/decimals).

## Inputs / Outputs
Called only by `internal/worker/handlers/recompute.go`, which loads inputs from SQL and persists the `Result` into `computed_grades`.

## Conventions & Constraints
- Keep this package pure and deterministic — no SQL, no context/tx, no time.Now. All persistence stays in the worker handler.
- Policy semantics (rounding mode, absent_counts_as, retake_policy, min_evaluated_weight_for_grade) must match `grading_scheme_versions` column semantics in `00001_initial_schema.sql`.
- No projections. `Result` deliberately carries no "range at term close": the norm has no notion of a forecast grade, and the columns that stored one were dropped in `00003`.
- Nothing here may write, suggest, or imply a nivel de logro. Keep the weighted result and the official record strictly separate.

## Change Log
- 2026-08-27: Dropped `ProjectedMinNormalized`/`ProjectedMaxNormalized` from `Result` and the lines computing them — the forecast was cut along with the rest of the predictive subsystem in `00003`. Package doc rewritten to state plainly that this is the optional internal system and not the MINEDU record, since the previous wording ("the grade.recompute math") read as though it produced the grade that matters.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
