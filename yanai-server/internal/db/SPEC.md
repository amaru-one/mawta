## Purpose
The pgx connection pool and the per-transaction tenant/RLS discipline, plus error mapping to HTTP-shaped app errors.

## Contents
- `db.go` — `DB` (pool wrapper), `Open`/`Close`, `TenantCtx{TenantID, ActorID, TeacherID, RequestID}`, `WithTenantTx` (SET LOCAL role `yanai_app` + GUCs `app.tenant_id`/`app.actor_id`/`app.request_id`, so context evaporates at commit/rollback), `WithSystemTx` (pool owner, bypasses RLS — cross-tenant maintenance only).
- `errors.go` — `AppError{Status, Code, Message}`, `NewAppError`, `MapError` translating pgx/Postgres errors (not-found, unique violations, check violations, RLS denials) into app errors.

## Inputs / Outputs
Input: `DATABASE_URL`. Output: transactions handed to `repo`, `httpapi`, and `worker` callbacks; `AppError` consumed by `httpapi/respond.go`.

## Conventions & Constraints
- All tenant data access goes through `WithTenantTx`; never run tenant queries on the raw pool.
- `WithSystemTx` is only for genuinely cross-tenant work (worker ticker, nil-tenant jobs) — never for request data.
- A zero `ActorID` means system/job actor (empty `app.actor_id`).

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
