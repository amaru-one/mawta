## Purpose
Go API powering the six Yanai screens on top of the Postgres schema in `migrations/`. Stack: chi + pgx/v5, hand-written SQL (no ORM/sqlc), an in-process Postgres-backed job queue, forced row-level security per tenant.

## Contents
- `cmd/api/` — the single binary entrypoint (see its SPEC.md).
- `internal/` — packages: `config`, `db`, `domain`, `grading`, `httpapi`, `media`, `repo`, `worker` (each with its own SPEC.md).
- `migrations/` — goose SQL migrations 00001–00006 + `ANALYSIS.md` (see its SPEC.md).
- `seed/` — demo tenant seed script, add-on scripts for extra classes/sections, + onboarding runbook (see its SPEC.md).
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
- **Evaluation is por criterios, not weighted.** RVM 094-2020 (mod. 048-2024) determines achievement per competencia from the teacher's judgement of evidence against the criterios de evaluación they wrote. The official record is `competency_term_levels`, written only by a teacher's explicit action and derived from nothing. Marks on quizzes and exams are evidence; they never feed a final grade arithmetically.
- `internal/grading` still computes a weighted grade, but only as the school's **optional internal system** (D.S. 009-2006-ED art. 37.4.f) — clearly labelled as such in the UI and walled off from the competency record. It is pure and SQL-free.
- Nothing predictive: no projections, no risk flags, no situación-final projection. The app records what teachers assert.
- Every tenant-scoped query runs under forced RLS via `db.WithTenantTx`; `WithSystemTx` (RLS bypass) is reserved for cross-tenant maintenance.
- Append-only score/grade history: corrections supersede rows (`superseded_at`), never update in place.
- No test suite exists yet; CI gate is `go vet` + `go build`.

## Change Log
- 2026-08-29: Purge pass. Deleted the end-of-period SIAGIE report end to end (`internal/repo/siagie.go`, its handler and route), eight further routes no client called, and the retired AI note-summary feature. The lesson roster stopped carrying a per-student nivel de logro, trend and participation rating, and `session_observations.participation_level` was dropped in `00006`. `internal/domain` lost the constant blocks for subsystems with no Go code left. The Contents line for `migrations/` had also been stale since the squash. See the SPEC.md of `internal/httpapi`, `internal/repo`, `internal/domain` and `migrations` for the reasoning.
- 2026-08-27: Realigned grading with RVM 094-2020: criterios de evaluación per competencia are now a first-class surface (schema `00003`, `internal/repo/criteria.go`, `internal/httpapi/criteria.go`, and the criterios screen in `yanai-ui`), the weighted result was demoted to a labelled internal system, and everything predictive was removed — `internal/promotion` (with the repo's only test file), both risk job kinds, and the `risk_*` tables. `internal/grading` survives as the internal system's math.
- 2026-08-26: `seed/`'s add-on scripts were folded back into `seed_demo_tenant.sql`; Contents line updated. `migrations/` squashed its 18-file history into `00001_initial_schema.sql`.
- 2026-08-25: `seed/` now holds add-on scripts alongside the demo seed (`add_class_ingles_5to_a.sql`); the Contents line was widened to say so.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
