## Purpose
Go API powering the Yanai app's screens on top of the Postgres schema in `migrations/`. Stack: chi + pgx/v5, hand-written SQL (no ORM/sqlc), an in-process Postgres-backed job queue, forced row-level security per tenant.

## Contents
- `cmd/api/` — the single binary entrypoint (see its SPEC.md).
- `cmd/useradd/` — creates or resets an account; the only way to a first login now `seed/` is gone (see its SPEC.md).
- `internal/` — packages: `auth`, `config`, `db`, `domain`, `grading`, `httpapi`, `media`, `repo`, `worker` (each with its own SPEC.md).
- `migrations/` — the schema as one goose migration, `00001_initial_schema.sql` (see its SPEC.md).
- `docs/` — local Postgres setup (see its SPEC.md).
- `Dockerfile` — production image build (distroless, ships `api`, `useradd`, goose + migrations).
- `README.md` — quick start, auth, route list.
- `.env` — local dev config pointing at the `yanai-pg` container (port 55432); not committed patterns live in `.gitignore`.
- `go.mod` / `go.sum` — module `yanai-server`; deps: chi, go-chi/cors, pgx/v5, google/uuid, joho/godotenv, golang.org/x/crypto (bcrypt), golang.org/x/term (hidden password prompt in `cmd/useradd`).
- `data/` — empty scratch dir.
- `.vscode/` — editor launch config (no spec).

## Inputs / Outputs
Consumes `DATABASE_URL` (Postgres 16 + pgvector) and env config (see `internal/config`). Serves HTTP on `HTTP_ADDR` (default :8080): `/healthz` plus `POST /api/v1/auth/login`/`logout` are public; every other `/api/v1/*` route requires the `yanai_session` HttpOnly cookie those set. Runs the background worker in-process when `WORKER_ENABLED`.

## Conventions & Constraints
- All SQL is hand-written in `internal/repo` and handlers; no ORM or code generation.
- **Evaluation is por criterios, not weighted.** RVM 094-2020 (mod. 048-2024) determines achievement per competencia from the teacher's judgement of evidence against the criterios de evaluación they wrote, each anchored to a capacidad of the competencia. The official record is `competency_term_levels`, written only by a teacher's explicit action and derived from nothing. A piece of evidence carries a `value_scale` of `numeric` or `rubric`: a numeric one gets an overall mark plus, optionally, per-criterio marks in `criterion_scores`; a rubric one is valued only through `criterion_scores` and never counts toward the school's internal average. None of these marks feed a final grade arithmetically.
- `internal/grading` still computes a weighted grade, but only as the school's **optional internal system** (D.S. 009-2006-ED art. 37.4.f) — clearly labelled as such in the UI and walled off from the competency record. It is pure and SQL-free.
- Nothing predictive: no projections, no risk flags, no situación-final projection. The app records what teachers assert.
- Every tenant-scoped query runs under forced RLS via `db.WithTenantTx`. `WithSystemTx` is not an RLS bypass: it opens a plain transaction on the pool's own connection and changes no role and no GUC, so its reach is a property of the caller's connection string, not of the function. From `cmd/api` (connected as `yanai_app`, a non-owner under `FORCE ROW LEVEL SECURITY`) it reaches only the tables with no policy at all, which is what the worker's nil-tenant job dispatch needs. From `cmd/useradd` (the superuser via `ADMIN_DATABASE_URL`) it also reaches `users` and `memberships`, which is what seeding the first account needs. Never for request data. See `internal/db/SPEC.md` for the full rule.
- Append-only score/grade history: corrections supersede rows (`superseded_at`), never update in place.
- CI gate is `go vet` + `go build` + `go test ./...` against a real Postgres 16.
- **Tests come in two kinds, and the difference is the point.** `internal/grading` and `classifyConclusionRequirement` are pure and run anywhere. Everything else needs a database and goes through `internal/dbtest`, which creates a throwaway one, migrates it, seeds fixtures and drops it — gated on `YANAI_TEST_ADMIN_URL`, skipping loudly without it. CI always sets it, so a run that skipped the database cannot be merged. Database tests live beside the package they exercise, never in a separate integration tree.
- **Never assert `err == nil` alone on an RLS-scoped read.** A query with no tenant set returns zero rows and succeeds, so a passing test proves nothing about isolation unless it counts rows.

## Open Questions
- None.
