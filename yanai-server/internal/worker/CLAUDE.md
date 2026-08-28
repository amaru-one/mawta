# CLAUDE.md

Guidance for working in `yanai-server/internal/worker` — the in-process background job
processor. Read this together with the repo-root `CLAUDE.md` (RLS, append-only tables,
migrations).

## Shape of the package

| File | Role |
| --- | --- |
| `worker.go` | `Run` fan-out, the claim loop, dispatch, success/failure bookkeeping |
| `registry.go` | `kind → HandlerFunc` map; the only place a job kind is wired up |
| `handlers/` | One file per operation, plus `common.go` for the package doc |

`handlers` deliberately does **not** import `worker`: handlers take plain arguments
(`jobID int64`, `payload []byte`) and `registry.go` adapts them to `HandlerFunc`.
Adding a `worker.Job` parameter to a handler creates an import cycle.

There is exactly one job kind:

```
score saved (httpapi)
  └─ grade.recompute
       writes computed_grades (+ components)
```

That chain maintains the school's **optional internal weighted system** only. Under
RVM 094-2020 achievement is the teacher's judgement of evidence against the criterios
de evaluación, recorded per competencia in `competency_term_levels` — asserted through
the HTTP API, never by a job. **No handler may write, suggest or imply a nivel de
logro.**

**There is no ticker and no scheduler.** Nothing in this package runs periodically or
enumerates tenants. All work descends from a teacher saving a score. This is deliberate: each verdict is a pure function of rows that only
change when a teacher acts.

## Runtime

`cmd/api/main.go` starts `worker.Run(ctx, database, cfg, logger)` in-process when
`WORKER_ENABLED` (default `true`). There is no separate worker binary — `Run` is the
seam that would let one exist later.

- `WORKER_CONCURRENCY` (default `2`) → that many `pollLoop` goroutines, each claiming
  independently via `FOR UPDATE SKIP LOCKED`.
- `WORKER_QUEUE` (default `"default"`) → the queue the claim query filters on.
  Note `repo.EnqueueJob` hardcodes `queue = 'default'`, so setting this to anything
  else means nothing gets claimed.
- Poll interval is 2s (`pollInterval`); there is no `LISTEN/NOTIFY`, so a freshly
  enqueued job waits up to 2s. A score save therefore shows up as a recomputed grade
  within a couple of seconds.

## Job lifecycle

1. **Claim** (`claim`): a single `UPDATE ... where id = (select ... for update skip locked limit 1)`
   flips `available|retryable|scheduled` → `running`, increments `attempts`, and stamps
   `attempted_at` / `attempted_by` (the hostname). Ordered by `priority, run_after, id`
   and served by the `jobs_claim_idx` partial index.
2. **Dispatch** (`dispatch`): looks the kind up in the registry. An unknown kind is a
   failure, not a panic — it burns an attempt and backs off. Rows left over from the
   retired kinds (`risk.detect`, `risk.term_failure`, `risk.promotion_projection`,
   `note_summary.generate`, `notification.sweep`, `retention.sweep`) will fail this way
   until discarded; that is expected.
3. **Run**: the handler executes inside one transaction (see below). Returning an error
   rolls back everything the handler wrote.
4. **Finalize**: `completed`, or `retryable` / `discarded` once `attempts >= max_attempts`
   (`max_attempts` defaults to 20 in the schema).

Backoff is `min(attempts^4, 3600)` seconds, written into `run_after`. Each failure
appends `{attempt, at, error}` to the `errors` jsonb array (error text truncated to 2000
chars). `finalized_at` is only set on the terminal transition, which is what keeps the
`jobs_finalized_consistent` check satisfied.

There is **no lease reaper**: a job whose worker dies mid-run stays `running` forever.
Diagnose with `attempted_by` / `attempted_at`; requeue by hand.

## Transactions and RLS

`dispatch` picks the transaction by tenant:

- `job.TenantID != uuid.Nil` → `db.WithTenantTx` with `RequestID = "job:" + kind` and a
  **zero `ActorID`** (so `app.actor_id` is empty and events are attributed to
  `actor_type = 'job'`). The handler runs as `yanai_app` under RLS.
- `job.TenantID == uuid.Nil` → `db.WithSystemTx` (pool owner, RLS bypassed).

Both current job kinds are enqueued **with** a tenant, so in practice handlers always run
under RLS. That is why handler SQL uses `app.current_tenant_id()` for `tenant_id` on
inserts and never filters by tenant explicitly — and why a handler that forgets the tenant
context sees zero rows rather than an error.

The nullable-tenant path now has no users. Don't reach for it just to make a query simpler.

## Enqueueing

Always `repo.EnqueueJob(ctx, tx, tenantID, kind, priority, payload, uniqueKey)` inside
the same transaction as the write that triggered it, so the enqueue is atomic with the
change it reacts to.

- `priority` is 1–4, **lower runs first**.
- `uniqueKey` dedupes against `jobs_unique_key_idx` while a job is
  `available|retryable|scheduled|running`. Empty string means no dedupe.
- Because dedupe covers `running`, a job enqueued while an identical one is mid-flight
  is dropped, not queued behind it. Keys are therefore built to be *coalescing*
  (recompute this student's grade) rather than *per-event*.

## Operations

### `grade.recompute` — `handlers/recompute.go`

| | |
| --- | --- |
| Enqueued by | `httpapi.enqueueGradeRecompute` (score create/correct in `internal/httpapi/grades.go`) |
| Priority | 2 |
| Unique key | `grade.recompute:<student>:<class>:<term>` |
| Payload | `{class_id, term_id, student_id?}` |

Recomputes the live `term_partial` `computed_grades` row for a class/term. With
`student_id` omitted it fans out over every student holding a live score in that
class/term (`GradeRecompute` → `recomputeOne` per student, all in **one** transaction —
a failure on student 40 rolls back the first 39).

Per student, `recomputeOne`:

1. Counts live scores; returns early if zero.
2. Reads `class_effective_grading_schemes` for the scheme + version; a `uuid.Nil`
   version means no published version in effect → no-op.
3. Loads the `grading.Policy` from `grading_scheme_versions`, the scale from
   `grade_scales`, and component weights from `grading_scheme_component_weights`.
4. Loads published assessments joined to the student's live scores (with any
   `retake_authorizations` cap), grouping attempts per assessment.
5. Calls `grading.Compute` — all the arithmetic (drops, retake caps, absent handling,
   rounding, projections) lives in `internal/grading`, not here. **Keep it that way**;
   this handler is I/O plus persistence.
6. Computes `inputs_digest = sha256(scheme_version_id | sorted live score ids)`. If it
   matches the live row's digest, the whole write is skipped.
7. Resolves `scale_level_id` from `grade_scale_levels` by normalized value (the
   `max_normalized = 1` disjunct is what makes a perfect score land in the top band).
   `display_value` is the level `code` for ordinal scales, otherwise the value projected
   onto `[scale_min, scale_max]` and rounded per policy.
8. Derives `trend` (`up`/`down`/`flat`) by comparing against the live row's normalized
   value — so trend is "since last recompute", not "since last term".
9. Supersedes the live row (`superseded_at = now()`), inserts the new
   `computed_grades` row with `supersedes_id` and `computed_by_job_id`, then inserts one
   `computed_grade_components` row per component.

`recomputeOne` returns `(wrote bool, err error)`. Nothing consumes that value any more:
it existed so `GradeRecompute` could chain a risk job when a grade actually changed, and
there is nothing left to chain. It is kept because "did this write?" is the honest
signature for the function.

Gotchas:

- `computed_grades` is append-only: the only permitted `UPDATE` is stamping
  `superseded_at`. Never patch a grade in place.
- The digest covers the scheme *version* and score ids only. Editing a scheme in place
  (rather than publishing a new version) will not invalidate cached grades.
- `scores_counted` is the raw live-score count from step 1, which can exceed the number
  of scores actually fed to `grading.Compute` (step 4 only joins **published**
  assessments).
- When `result.BelowMinEvaluated`, both `scale_level_id` and `display_value` are left
  null — the row still exists, carrying the weights it was computed over.

## Adding a job kind

1. Add the constant to `internal/domain/consts.go` (`JobKind*`) — kinds are strings in
   the DB, so the constant is the only guard against typos.
2. Write `handlers/<kind>.go` with signature `func X(ctx, tx pgx.Tx, [jobID int64,] payload []byte) error`.
   Keep the rules in a pure package (`internal/grading`) and the handler to I/O — that is what makes the rules testable without a database.
   Take `jobID` only if you need to stamp `*_by_job_id`.
3. Wire it into `defaultRegistry()` in `registry.go`.
4. Enqueue with `repo.EnqueueJob` from inside the triggering transaction; pick a
   coalescing unique key.
5. Add a migration updating the `jobs.kind` column comment. `jobs.kind` is plain text
   with no CHECK, so that migration is documentation only.

Handler rules of thumb:

- Idempotent: a job can run twice (retry after a commit-time failure, manual requeue).
- Everything in one transaction — don't spawn your own; you already have `tx`.
- Insert with `app.current_tenant_id()`, never a tenant id from the payload.
- Long fan-outs (`GradeRecompute` over a whole class) hold one transaction for the whole
  run. If a kind ever needs to touch thousands of rows, split it into per-entity jobs
  rather than widening the transaction.
- Never `UPDATE` `scores` or `computed_grades` except to stamp `superseded_at`.

## Testing / running

There is no test suite in `yanai-server` yet, and none for this package. To exercise the
chain end to end: run the API (`go run ./cmd/api`) with `WORKER_ENABLED=true`, post two
low scores for one student, then inspect —

```sql
select id, kind, status, attempts, errors from jobs order by id desc limit 10;
-- expect exactly one grade.recompute, completed, and nothing chained after it

select display_value, total_weight, evaluated_weight
  from computed_grades where superseded_at is null;
```

Use `HTTP_ADDR=:8099` to run alongside an API already holding port 8080.

To run the API without background work, set `WORKER_ENABLED=false`; jobs then accumulate
as `available` and can be inspected before any handler touches them.
