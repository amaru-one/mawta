## Purpose
Pure grade-computation math for `grade.recompute`: turns a student's attempts + component weights + scheme policy into a normalized term grade. No I/O.

**This is the school's optional internal weighted system, never the official record.** RVM 094-2020 (mod. 048-2024) determines achievement per competencia from the teacher's judgement of evidence against the criterios de evaluación, with no weighted average anywhere; that record is `competency_term_levels` and nothing here feeds it. A private IE may run its own internal numeric system (D.S. 009-2006-ED art. 37.4.f) — that is what this computes.

## Contents
- `compute.go` — input types (`Attempt`, `AssessmentInput`, `ComponentWeight`, `Policy`), outputs (`ComponentResult`, `Result` incl. `BelowMinEvaluated`, counted/dropped/excused score ids), `resolveAssessment` (per-assessment attempt resolution: retake policy, caps, absent handling), `Compute` (weighting, drop-lowest-N, aggregation, evaluated-weight ratio), and `Round` (rounding modes/decimals).
- `compute_test.go` — table-driven tests, no database and no build tag: this package's purity is what makes them runnable anywhere, so a change that needs I/O here breaks them by design. Covers the four retake policies (including `none` falling back when attempt 1 is absent, and `capped` clamping retakes only), `absent_counts_as`, graded rows with no usable value being dropped rather than counted as zero, the five aggregations, `drop_lowest_n` clamping to keep at least one, required-vs-optional ungraded components, `BelowMinEvaluated`, and every rounding mode. `drop_lowest_n` is also pinned by identity, not only by count: the dropped score id, the counted score ids, and that the two sets are disjoint — a version that dropped the right number of assessments while naming the wrong ones still produces the same mean, so the counts alone cannot catch it.

## Inputs / Outputs
Called only by `internal/worker/handlers/recompute.go`, which loads inputs from SQL and persists the `Result` into `computed_grades`.

## Conventions & Constraints
- Keep this package pure and deterministic — no SQL, no context/tx, no time.Now. All persistence stays in the worker handler.
- Policy semantics (rounding mode, absent_counts_as, retake_policy, min_evaluated_weight_for_grade) must match `grading_scheme_versions` column semantics in `00001_initial_schema.sql`.
- No projections. `Result` deliberately carries no "range at term close": the norm has no notion of a forecast grade.
- Nothing here may write, suggest, or imply a nivel de logro. Keep the weighted result and the official record strictly separate.
- `Compute` divides by **evaluated** weight, not total: a term that is only half marked reports the grade earned so far, not a grade halved by the marking that has not happened yet. `BelowMinEvaluated` is how a caller learns the term is thinly evidenced; it is a flag, never a penalty applied to the number.
- `Round`'s `half_up` is `floor(x+0.5)`, which rounds negatives towards positive infinity rather than away from zero. Grades are never negative so nothing depends on it, but it is pinned by a test — change it deliberately or not at all.

## Open Questions
- None.
