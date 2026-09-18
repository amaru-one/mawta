## Purpose
Go API powering the Yanai app's screens on top of the Postgres schema in `migrations/`. Stack: chi + pgx/v5, hand-written SQL (no ORM/sqlc), an in-process Postgres-backed job queue, forced row-level security per tenant.

## Contents
- `cmd/api/` — the single binary entrypoint (see its SPEC.md).
- `cmd/useradd/` — creates or resets an account; the only way to a first login now `seed/` is gone (see its SPEC.md).
- `internal/` — packages: `auth`, `config`, `db`, `domain`, `grading`, `httpapi`, `media`, `repo`, `worker` (each with its own SPEC.md).
- `migrations/` — the schema as goose migrations: `00001_initial_schema.sql` (the baseline) + `00002_auth.sql` (real authentication) (see its SPEC.md). Append-only: new schema work is always a new numbered file, never a rewrite or renumbering of an existing one.
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
- **Evaluation is por criterios, not weighted.** RVM 094-2020 (mod. 048-2024) determines achievement per competencia from the teacher's judgement of evidence against the criterios de evaluación they wrote. The official record is `competency_term_levels`, written only by a teacher's explicit action and derived from nothing. Marks on quizzes and exams are evidence; they never feed a final grade arithmetically.
- `internal/grading` still computes a weighted grade, but only as the school's **optional internal system** (D.S. 009-2006-ED art. 37.4.f) — clearly labelled as such in the UI and walled off from the competency record. It is pure and SQL-free.
- Nothing predictive: no projections, no risk flags, no situación-final projection. The app records what teachers assert.
- Every tenant-scoped query runs under forced RLS via `db.WithTenantTx`; `WithSystemTx` (RLS bypass) is reserved for cross-tenant maintenance.
- Append-only score/grade history: corrections supersede rows (`superseded_at`), never update in place.
- No test suite exists yet; CI gate is `go vet` + `go build`.

## Open Questions
- None.
