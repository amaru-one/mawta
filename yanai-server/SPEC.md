## Purpose
Go API powering the six Yanai screens on top of the Postgres schema in `migrations/`. Stack: chi + pgx/v5, hand-written SQL (no ORM/sqlc), an in-process Postgres-backed job queue, forced row-level security per tenant.

## Contents
- `cmd/api/` — the single binary entrypoint (see its SPEC.md).
- `internal/` — packages: `config`, `db`, `domain`, `grading`, `httpapi`, `media`, `repo`, `worker` (each with its own SPEC.md).
- `migrations/` — goose SQL migrations 00001–00016 + `ANALYSIS.md` (see its SPEC.md).
- `seed/` — demo tenant seed script + onboarding runbook (see its SPEC.md).
- `docs/` — local Postgres setup (see its SPEC.md).
- `bruno/` — OpenAPI collection for the Bruno API client (see its SPEC.md).
- `Dockerfile` — production image build (distroless, ships goose + migrations).
- `README.md` — quick start, dev-header auth, route list.
- `yanai-schema-prompt.md` — the original prompt used to generate the database schema from `yanai-views.html`.
- `.env` — local dev config pointing at the `yanai-pg` container (port 55432); not committed patterns live in `.gitignore`.
- `go.mod` / `go.sum` — module `yanai-server`; deps: chi, pgx/v5, google/uuid, joho/godotenv.
- `data/` — empty scratch dir.
- `.vscode/` — editor launch config (no spec).

## Inputs / Outputs
Consumes `DATABASE_URL` (Postgres 16 + pgvector) and env config (see `internal/config`). Serves HTTP on `HTTP_ADDR` (default :8080): `/healthz` plus `/api/v1/*` requiring `X-Tenant-ID` / `X-Actor-ID` dev headers. Runs the background worker in-process when `WORKER_ENABLED`.

## Conventions & Constraints
- All SQL is hand-written in `internal/repo` and handlers; no ORM or code generation.
- Every tenant-scoped query runs under forced RLS via `db.WithTenantTx`; `WithSystemTx` (RLS bypass) is reserved for cross-tenant maintenance.
- Append-only score/grade history: corrections supersede rows (`superseded_at`), never update in place.
- No test suite exists yet; CI gate is `go vet` + `go build`.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
