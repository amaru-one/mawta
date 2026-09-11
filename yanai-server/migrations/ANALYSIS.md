# Yanai schema — notes on the model

Companion to `00001`–`00014`. Covers the queries expected to hurt, the places
the HTML was ambiguous, and the constraints from the brief I would argue with.
(The HTML in question, `yanai-views.html`, was removed from the repo on
2026-08-29 — see root `SPEC.md`. This document is a dated design record and
is left as originally written; the per-folder SPEC.md files are now the
product spec of record.)
Predates `00002_evaluation_criteria.sql` (added 2026-08-26, after the first
squash); the reasoning below still holds, but every object count in this
document is from before it — see `SPEC.md`'s Change Log for what `00002` and
everything after it added and removed.

Superseded counts, kept only to date this document: the first squash's 55 base
tables became 60 after `00002` added five, then 78 after the **second squash
(2026-09-10)** folded `00002`–`00009` back into `00001`. A **third pass
(2026-09-11)**, a dead-schema cleanup rather than a squash — see
`SPEC.md`'s Change Log — dropped six more whole tables and 27 individual
columns that no Go or `yanai-ui` code referenced. The live figure is now
**72 base tables** in `public` (including `goose_db_version` and the `events`
partitions), 45 with FORCE RLS, 333 indexes, 431 constraints, 18 `app.*`
functions and **no `privacy.*` function** (`privacy.anonymize_student()` was
one of the drops; the three `privacy.*` views survive) and 81 non-internal
triggers. `evaluation_criterion_scores` is gone (a criterio is a tag, never a
score), as are the predictive and per-session-observation subsystems this
document still describes below, along with `assessment_templates`,
`note_summaries`, `deletion_requests` and `term_grade_snapshots` (2026-09-11).

## Verification

Every migration was applied against PostgreSQL 16 (`pgvector/pgvector:pg16`):

- `up` × 14 clean, `down` × 14 clean, `up` again clean, with zero residue
  (no leftover tables, schemas, roles, or the `timerange` type). The
  migrations folder holds schema only now — seed/demo data lives outside it
  in `seed/seed_demo_tenant.sql` (see that directory's `README.md`), so the
  checks below additionally require applying that script; they are not
  exercised by the schema migrations alone.
- 49 tables, 48 with RLS (`jobs` is the deliberate exception — workers span
  tenants), 350 indexes, 181 check constraints, 164 FKs, 6 exclusion
  constraints, 51 commented tables, 155 commented columns.
- Tenant isolation tested with a second tenant: a query with no tenant
  predicate returns only the session tenant's rows; with `app.tenant_id` unset
  it returns **zero** rows, not all rows; a cross-tenant `INSERT` is rejected by
  `WITH CHECK`.
- Screen 04's arithmetic recomputed from raw scores alone, with no reference to
  any stored derivation: `evaluated_weight 0.600000`, `achieved 0.83333`,
  `floor 0.50000`, `ceiling 0.90000` — matching the card exactly, and matching
  the stored `computed_grades` row.
- `privacy.undeclared_student_references` returns 0 rows.

Two real bugs surfaced only because the migrations were executed, and both are
fixed:

1. **The score-correction path was impossible.** `scores` had both
   `supersedes_id` and `superseded_by_id`, with a check that `superseded_at` and
   `superseded_by_id` be set together. But `scores_live_attempt_key` is a
   *partial* unique index, so it cannot be `DEFERRABLE`, so the replacement row
   cannot exist until the old one is closed — and the old one could not be
   closed without naming a replacement that did not exist yet. The forward
   pointer is now gone on both `scores` and `computed_grades`; the link points
   backwards only.
2. **The closed-term guard never fired.** `forbid_closed_term` and
   `sync_denormalised` were both `BEFORE INSERT` on `scores`. Postgres fires row
   triggers in *name* order, so `forbid_closed_term` ran first, read a still-null
   `term_id`, looked up nothing, and passed. Grades could be written into a
   closed term — precisely what constraint 3 exists to prevent. The check now
   lives inside `sync_score_denormalised`, the one function that knows the value.

   Generalising: **a guard that reads a denormalised column must live in the same
   trigger function that populates it.** Splitting them creates a silent
   ordering dependency on trigger names.

## The three queries I expect to be slowest

### 1. Grade recomputation for a class-term, with drop-lowest-N

The hot path. Fires on every score save (debounced through `jobs`) and for every
student in a class when a scheme version changes. For each student it gathers
live scores across all published assessments in the term, buckets them by
component, applies `drop_lowest_n` — a window function partitioned by
`(student_id, component_id)` — aggregates per `aggregation` mode, applies the
late penalty from `late_days`, normalises, looks up the band, compares against
the previous row, and writes.

Cost is not per-row, it is per-invocation: 30 students × ~5 components × several
assessments each, with a sort per partition. `scores_class_term_idx` keeps the
read to one index scan, and `inputs_digest` prevents writing a new
`computed_grades` row when nothing material changed. Without that digest the
table grows on every keystroke.

If it becomes a problem, the fix is to recompute one student rather than the
class on interactive saves, and reserve the class-wide pass for scheme changes
and term close.

### 2. The grading-coverage anti-join ("Notas reg.", "3 alumnos pendientes")

```
published assessments already due  ×  roster active on the due date
   ANTI JOIN  live scores
```

Per class this is trivial. The problem is the nightly reminder sweep, which runs
it for **every class in every tenant** to generate screen 05's "3 notas
pendientes". That is O(classes × students × assessments) across the whole
database — the one query whose cost is driven by tenant count rather than by
what a teacher is looking at.

`assessments_due_idx` (partial, `status = 'published'`) and
`scores_assessment_idx` (partial, live rows only) keep each unit cheap. At scale
this should become an incremental sweep keyed on
`assessments.due_at` crossing `now()`, not a full re-evaluation, and
`notifications.dedupe_key` already prevents the re-notification storm that would
otherwise follow.

### 3. Consecutive-absence detection over `attendance_records`

The `3 ausencias seguidas` rule needs each student's attendance in date order and
a gaps-and-islands window over it. `attendance_records` is the second-largest
table in the schema — 100k students × 4 sessions/week × 40 weeks is roughly 16M
rows a year — and the rule is evaluated for every tracked student.

`attendance_records_student_date_idx` on `(student_id, session_date desc)` makes
one student's history an index-only scan, which is why `session_date` is
denormalised onto the row at all: without it, ordering requires joining
`class_sessions` and sorting. The rule should evaluate only students with
attendance activity since the last run, driven off `events`, rather than
sweeping the roster.

**Honest caveat:** these are reasoned, not measured. The seed tenant is 30
students; nothing here has been benchmarked at the stated scale, and the ranking
should be re-derived from `pg_stat_statements` once there is real traffic.

Runner-up worth watching: time-series feature extraction over `events` for model
training. Monthly partitioning means a period query touches few partitions, but
a full-history training pull is a sequential scan of everything. That is
acceptable for a batch job and unacceptable for anything interactive.
