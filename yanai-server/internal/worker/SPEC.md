## Purpose
The in-process background job processor: a `SELECT ... FOR UPDATE SKIP LOCKED` claim loop over the `jobs` table, a handler registry keyed by job kind, exponential-backoff retries, and a ticker that enqueues per-tenant maintenance sweeps.

## Contents
- `worker.go` — `Run` (spawns `WORKER_CONCURRENCY` poll loops + the ticker), `Job`, `HandlerFunc`, claim/dispatch/success/failure bookkeeping (backoff `min(attempts^4, 3600)`s, error records appended to `jobs.errors`).
- `registry.go` — `defaultRegistry()`: the only place a job kind is wired to its handler; adapts `handlers` plain-argument functions to `HandlerFunc`.
- `ticker.go` — every 10 minutes (and once at startup) enumerates active tenants as the pool owner (the one sanctioned RLS bypass) and enqueues `notification.sweep` + `retention.sweep` per tenant with a per-day unique key.
- `handlers/` — one file per job kind (see its SPEC.md).
- `CLAUDE.md` — deep operational reference for this package: lifecycle, transactions/RLS, per-operation details and gotchas, how to add a job kind. Read it alongside this spec.

## Inputs / Outputs
Inputs: rows in `jobs` (enqueued by `repo.EnqueueJob` from `httpapi` and the ticker), config (`WORKER_ENABLED/CONCURRENCY/QUEUE`). Outputs: computed grades, risk flags, notifications, note summaries, audit events; job rows finalized as completed/retryable/discarded.

## Conventions & Constraints
- Tenant jobs run in `db.WithTenantTx` (RLS, actor_type 'job'); nil-tenant jobs in `WithSystemTx`. Handlers must be idempotent and use `app.current_tenant_id()` for inserts.
- `handlers` must not import `worker` (import cycle) — handlers take plain args (`jobID int64`, `payload []byte`).
- `repo.EnqueueJob` hardcodes queue 'default'; changing `WORKER_QUEUE` alone means nothing is claimed.
- No lease reaper: a job whose worker dies stays `running`; diagnose via `attempted_by`/`attempted_at`.
- New job kinds: constant in `domain/consts.go` → handler file → `defaultRegistry()` → enqueue with a coalescing unique key (see CLAUDE.md checklist).

## Change Log
- 2026-08-24: Initial spec created retroactively; CLAUDE.md added earlier the same day documents operations in depth.

## Open Questions
- None.
