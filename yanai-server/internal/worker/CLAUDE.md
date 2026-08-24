# CLAUDE.md

Guidance for working in `yanai-server/internal/worker` — the in-process background job
processor. Read this together with the repo-root `CLAUDE.md` (RLS, append-only tables,
migrations).

## Shape of the package

| File | Role |
| --- | --- |
| `worker.go` | `Run` fan-out, the claim loop, dispatch, success/failure bookkeeping |
| `registry.go` | `kind → HandlerFunc` map; the only place a job kind is wired up |
| `ticker.go` | Periodic enqueue of the per-tenant sweeps |
| `handlers/` | One file per operation, plus `common.go` for shared helpers |

`handlers` deliberately does **not** import `worker`: handlers take plain arguments
(`jobID int64`, `payload []byte`) and `registry.go` adapts them to `HandlerFunc`.
Adding a `worker.Job` parameter to a handler creates an import cycle.

## Runtime

`cmd/api/main.go` starts `worker.Run(ctx, database, cfg, logger)` in-process when
`WORKER_ENABLED` (default `true`). There is no separate worker binary — `Run` is the
seam that would let one exist later.

- `WORKER_CONCURRENCY` (default `2`) → that many `pollLoop` goroutines, each claiming
  independently via `FOR UPDATE SKIP LOCKED`.
- `WORKER_QUEUE` (default `"default"`) → the queue the claim query filters on.
  Note `repo.EnqueueJob` hardcodes `queue = 'default'`, so setting this to anything
  else means nothing gets claimed.
- One extra goroutine runs `tickerLoop`.
- Poll interval is 2s (`pollInterval`); there is no `LISTEN/NOTIFY`, so a freshly
  enqueued job waits up to 2s.

## Job lifecycle

1. **Claim** (`claim`): a single `UPDATE ... where id = (select ... for update skip locked limit 1)`
   flips `available|retryable|scheduled` → `running`, increments `attempts`, and stamps
   `attempted_at` / `attempted_by` (the hostname). Ordered by `priority, run_after, id`
   and served by the `jobs_claim_idx` partial index.
2. **Dispatch** (`dispatch`): looks the kind up in the registry. An unknown kind is a
   failure, not a panic — it burns an attempt and backs off.
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

Every job kind currently in the registry is enqueued **with** a tenant, so in practice
handlers always run under RLS. That is why handler SQL uses `app.current_tenant_id()`
for `tenant_id` on inserts and never filters by tenant explicitly — and why a handler
that forgets the tenant context sees zero rows rather than an error.

The nullable-tenant path exists for genuinely cross-tenant maintenance; don't reach for
it just to make a query simpler.

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

Gotchas:

- `computed_grades` is append-only: the only permitted `UPDATE` is stamping
  `superseded_at`. Never patch a grade in place.
- The digest covers the scheme *version* and score ids only. Editing a scheme in place
  (rather than publishing a new version) will not invalidate cached grades.
- `scores_counted` is the raw live-score count from step 1, which can exceed the number
  of scores actually fed to `grading.Compute` (step 4 only joins **published**
  assessments).
- When `result.BelowMinEvaluated`, both `scale_level_id` and `display_value` are left
  null — the row still exists, carrying the projected min/max range.

### `risk.detect` — `handlers/risk.go`

| | |
| --- | --- |
| Enqueued by | `internal/httpapi/session.go` — marking a student absent (priority 2), and mark-all-present (priority 3) |
| Unique key | `risk.detect:<student>:<class>` or `risk.detect:<class>` |
| Payload | `{class_id, student_id?}` |

Evaluates every active row in `risk_rules` against one student or, with `student_id`
omitted, the roster as of the tenant's today (`repo.RosterAsOf` + `tenantToday`).

Dispatch is on `rule.Code`; two codes are implemented, and an unrecognised code is
silently ignored:

- **`consecutive_absences`** — reads the last 10 `attendance_records` newest-first and
  counts the leading run of `absent`, stopping at the first non-absent. Fires when the
  run reaches `params.consecutive_absences` (default 3).
- **`level_drop`** — reads the live `computed_grades` row; requires `trend = 'down'`
  with both current and previous `scale_level_id` set, and fires when
  `previous.ordinal - current.ordinal >= params.min_drop` (default 1).
  `params.level_drop_sessions` (default 3) is used **only in the message text**, not in
  the condition.

When a condition holds, `upsertRiskFlag` opens or refreshes the single active flag for
`(student, class, rule)`. Its `on conflict` target reproduces the `risk_flags_open_key`
partial unique index *exactly*, `coalesce(class_id, '000…0')` included — change the
index and you must change this clause. `returning id, (xmax = 0)` distinguishes insert
from update; evidence rows and the alert notification are written **only on a fresh
insert**, so a flag that stays true just gets `last_evaluated_at` bumped and never
re-notifies.

When the condition does not hold, `resolveFlagIfActive` closes any active flag
(`status = 'resolved'`, `resolved_at = now()`). Re-triggering later opens a new flag,
which does notify again.

Notifications are deduped on `(recipient_teacher_id, dedupe_key)` where
`dedupe_key = <category>:<student>:<class>`. The recipient is the class's current
`titular`; if there isn't one, the whole handler returns nil (no flags written at all,
not just no notification).

### `note_summary.generate` — `handlers/summary.go`

| | |
| --- | --- |
| Enqueued by | `internal/httpapi/grades.go` (teacher-requested summary) |
| Priority | 2 |
| Unique key | `note_summary.generate:<student>:<class>:<term>` |
| Payload | `{student_id, class_id?, term_id?, requested_by}` |

**Deterministic extractive stub — no AI provider is called at this stage**
(`model = 'extractive-stub-v1'`). Replace `firstSentence`-based bullet building when a
provider is wired in; the surrounding row lifecycle should stay.

1. Marks any existing `ready`/`generating` summary for the same scope `stale`.
2. Inserts a new `generating` row; `scope` is `student_class_term` when both class and
   term are present, otherwise `student_term`.
3. Loads the student's `saved` voice notes newest-first, filtered by `class_id` when
   given. **`term_id` never filters the notes** — it only participates in scope and
   staleness matching.
4. No notes → the row goes to `failed` with `error_detail = 'sin notas de voz guardadas'`
   (a legitimate outcome; the job itself still succeeds).
5. Otherwise takes the first sentence of up to 5 transcripts, appends a
   `"N notas sin transcribir"` bullet if there's room, and flips the row to `ready` with
   `notes_count` = **all** loaded notes (not just the bulleted ones) and
   `generated_by_job_id`.
6. Inserts a `note_summary_sources` row per note, then logs
   `note_summary.generated` via `repo.LogJobEvent`.

Gotcha: `firstSentence` truncates with a byte slice (`s[:140]`), which can split a
multi-byte character in Spanish text. Fix with runes if the output is ever shown raw.

### `notification.sweep` — `handlers/sweep.go`

| | |
| --- | --- |
| Enqueued by | `ticker.go`, per active tenant |
| Priority | 4 |
| Unique key | `notification.sweep:<tenant>:<YYYY-MM-DD>` (one per tenant per UTC day) |
| Payload | `{tenant_id}` — **ignored**; the handler works off the tenant session context |

Two pure-SQL inserts, both `on conflict (recipient_teacher_id, dedupe_key) ... do nothing`,
so a condition the teacher has already been told about never re-notifies:

- **`attendance_unmarked`** — `class_sessions` in the last 7 days that are
  `in_progress`/`completed` with `attendance_taken_at is null`. Dedupe key
  `attendance_unmarked:<session_id>`, expires after 7 days.
- **`grades_pending`** — `published` assessments past `due_at` with at least one
  currently-enrolled student having no live score. Dedupe key
  `grades_pending:<assessment_id>`, no expiry.

Both target the class's current `titular` via `class_teachers`. Note these queries use
Postgres `current_date` (session timezone), not the tenant timezone helper
`tenantToday` — a deliberate simplification, but it does mean tenants far from UTC can
see a sweep run against the wrong day boundary.

### `retention.sweep` — `handlers/retention.go`

| | |
| --- | --- |
| Enqueued by | `ticker.go`, per active tenant |
| Priority | 4 |
| Unique key | `retention.sweep:<tenant>:<YYYY-MM-DD>` |
| Payload | `{tenant_id}` — ignored |

**Non-destructive stub.** Counts `students` and `voice_notes` past `retention_until`
(and not yet anonymised/purged) and writes the counts to `events` as
`retention.sweep_report` via `repo.LogJobEvent`. It deletes and anonymises nothing —
actual erasure is meant to run through `privacy.deletion_requests`. Keep it read-only
until that path exists; hard `DELETE` is trigger-blocked on these tables anyway.

## The ticker

`tickerLoop` fires once at startup and then every 10 minutes (`tickerInterval`). It
enumerates active tenants with a **plain pool query as the owner, bypassing RLS** — the
one sanctioned use of that privilege in the codebase, deliberately confined here — then
enqueues the two sweeps per tenant inside a `WithSystemTx`.

The daily unique key is what makes a 10-minute ticker safe: re-enqueues collapse into
the day's existing job. Consequently the sweeps run at most once per tenant per UTC day,
and the ticker interval only affects how soon after a restart they fire.

Each tenant's enqueue is its own transaction, so one failing tenant doesn't block the
rest (the error is logged and the loop continues).

## Adding a job kind

1. Add the constant to `internal/domain/consts.go` (`JobKind*`) — kinds are strings in
   the DB, so the constant is the only guard against typos.
2. Write `handlers/<kind>.go` with signature `func X(ctx, tx pgx.Tx, [jobID int64,] payload []byte) error`.
   Take `jobID` only if you need to stamp `*_by_job_id`.
3. Wire it into `defaultRegistry()` in `registry.go`.
4. Enqueue with `repo.EnqueueJob` from inside the triggering transaction; pick a
   coalescing unique key.
5. Update the `jobs.kind` column comment in `migrations/00013_events_and_jobs.sql` if
   the kind list there is now stale.

Handler rules of thumb:

- Idempotent: a job can run twice (retry after a commit-time failure, manual requeue).
- Everything in one transaction — don't spawn your own; you already have `tx`.
- Insert with `app.current_tenant_id()`, never a tenant id from the payload.
- Long fan-outs (`GradeRecompute` over a whole class) hold one transaction for the whole
  run. If a kind ever needs to touch thousands of rows, split it into per-entity jobs
  rather than widening the transaction.
- Never `UPDATE` `scores` or `computed_grades` except to stamp `superseded_at`.

## Testing / running

There is no test suite in `yanai-server` yet, and none for this package. To exercise a
handler end to end: run the API (`go run ./cmd/api`) with `WORKER_ENABLED=true`, trigger
the originating HTTP route, then inspect the row —

```sql
select id, kind, status, attempts, run_after, errors from jobs order by id desc limit 20;
```

To run the API without background work, set `WORKER_ENABLED=false`; jobs then accumulate
as `available` and can be inspected before any handler touches them.
