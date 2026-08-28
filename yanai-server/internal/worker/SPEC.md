## Purpose
The in-process background job processor: a `SELECT ... FOR UPDATE SKIP LOCKED` claim loop over the `jobs` table, a handler registry keyed by job kind, and exponential-backoff retries. Runs exactly one kind: `grade.recompute`, which maintains the school's optional internal weighted grade. Nothing here touches the official record — the nivel de logro per competencia is asserted by a teacher through the HTTP API (RVM 094-2020).

## Contents
- `worker.go` — `Run` (spawns `WORKER_CONCURRENCY` poll loops), `Job`, `HandlerFunc`, claim/dispatch/success/failure bookkeeping (backoff `min(attempts^4, 3600)`s, error records appended to `jobs.errors`).
- `registry.go` — `defaultRegistry()`: the only place a job kind is wired to its handler; adapts `handlers` plain-argument functions to `HandlerFunc`.
- `handlers/` — one file per job kind (see its SPEC.md).
- `CLAUDE.md` — deep operational reference for this package: lifecycle, transactions/RLS, how to add a job kind. Read it alongside this spec.

## Inputs / Outputs
Inputs: rows in `jobs` (enqueued by `repo.EnqueueJob` from `httpapi` score writes). Outputs: `computed_grades` + `computed_grade_components`; job rows finalized as completed/retryable/discarded.

## Conventions & Constraints
- Tenant jobs run in `db.WithTenantTx` (RLS, actor_type 'job'); nil-tenant jobs in `WithSystemTx`. Handlers must be idempotent and use `app.current_tenant_id()` for inserts.
- `handlers` must not import `worker` (import cycle) — handlers take plain args (`jobID int64`, `payload []byte`).
- `repo.EnqueueJob` hardcodes queue 'default'; changing `WORKER_QUEUE` alone means nothing is claimed.
- **There is no ticker and no scheduler.** All work is event-driven off a teacher saving a score. Nothing runs periodically; nothing scans tenants.
- Rules live in a pure package (`internal/grading`); handlers are I/O only.
- **No job may write or suggest a nivel de logro.** Asserting one is a teacher's act, and the worker has no path to `competency_term_levels`.
- No lease reaper: a job whose worker dies stays `running`; diagnose via `attempted_by`/`attempted_at`.
- New job kinds: constant in `domain/consts.go` → handler file → `defaultRegistry()` → enqueue with a coalescing unique key (see CLAUDE.md checklist).

## Change Log
- 2026-08-27: Down to one job kind. Deleted the `risk.term_failure` and `risk.promotion_projection` handlers and their registry entries, along with `internal/promotion` and the `risk_*` tables (see `migrations/SPEC.md` `00003`) — everything predictive was cut so the app records what teachers assert and nothing else. `grade.recompute` survives, now explicitly serving the optional internal weighted system rather than anything official, and no longer chains a follow-up job.
- 2026-08-26: Added `risk.promotion_projection` (handlers/promotion.go), the first job that reads the *asserted* record rather than the computed suggestion. `risk.term_failure` was re-anchored off `grade_scales.passing_value` — which encoded a 2020-only rule — onto the lowest band's ceiling, and its wording now states that it is a suggestion. See `CLAUDE.md` for both.
- 2026-08-25: Reduced to two job kinds. Deleted `ticker.go` and the `risk.detect`, `note_summary.generate`, `notification.sweep`, `retention.sweep` handlers; added `risk.term_failure`, chained off `grade.recompute` instead of a schedule. Verified end to end against the demo tenant (flag opens, refreshes idempotently, auto-resolves on recovery).
- 2026-08-24: Initial spec created retroactively; CLAUDE.md added earlier the same day documents operations in depth.

## Open Questions
- None.
