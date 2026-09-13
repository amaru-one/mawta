## Purpose
Go API powering the Yanai app's screens on top of the Postgres schema in `migrations/`. Stack: chi + pgx/v5, hand-written SQL (no ORM/sqlc), an in-process Postgres-backed job queue, forced row-level security per tenant.

## Contents
- `cmd/api/` — the single binary entrypoint (see its SPEC.md).
- `cmd/useradd/` — creates or resets an account; the only way to a first login now `seed/` is gone (see its SPEC.md).
- `internal/` — packages: `auth`, `config`, `db`, `domain`, `grading`, `httpapi`, `media`, `repo`, `worker` (each with its own SPEC.md).
- `migrations/` — the schema as goose migrations: `00001_initial_schema.sql` (the baseline) + `00002_auth.sql` (real authentication) (see its SPEC.md). Append-only: new schema work is always a new numbered file, never a rewrite or renumbering of an existing one.
- `docs/` — local Postgres setup (see its SPEC.md).
- `bruno/` — OpenAPI collection for the Bruno API client (see its SPEC.md).
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

## Change Log
- 2026-09-13: Migrations are append-only from now on — no renumbering, no rewriting an applied file, no folding files back into `00001`. The `migrations/` Contents line above says so and drops its "squashed baseline" wording; the rule and its reason live in `migrations/SPEC.md`'s Conventions.
- 2026-09-11: **Real authentication.** Username + bcrypt password, an HttpOnly session cookie, a server-side `user_sessions` table (`migrations/00002_auth.sql`). `internal/httpapi.sessionAuth` replaces the old dev-header `tenantAuth`. New `internal/auth` (hashing/tokens) and `cmd/useradd` (the seed's replacement for creating a first account — it creates only the account, not academic data). `memberships.role` collapsed to `('teacher','student','supervisor','admin')`; only `teacher` can log in today. `seed/` is gone; the Dockerfile no longer copies it and now ships `useradd`. See `migrations/SPEC.md`, `internal/httpapi/SPEC.md`, `internal/db/SPEC.md`, `internal/repo/SPEC.md`, `internal/domain/SPEC.md`, `internal/config/SPEC.md`, `internal/auth/SPEC.md`, `cmd/useradd/SPEC.md`.
- 2026-09-11: **Dead-schema cleanup in `migrations/`** — six whole tables (`assessment_templates`, `assessment_template_competencies`, `note_summaries`, `note_summary_sources`, `deletion_requests`, `term_grade_snapshots`) and 27 columns across 12 surviving tables dropped, none of them referenced by any Go or `yanai-ui` code. `go build ./...` and `go vet ./...` clean against the resulting schema — nothing here needed a change, confirming the columns really were unread. Full accounting in `migrations/SPEC.md`'s Change Log.
- 2026-09-10: **`migrations/` is one file again.** `00001`–`00009` squashed back into `00001_initial_schema.sql`: the eight migrations added since the 2026-08-26 squash had re-accumulated the create-then-drop churn that squash existed to remove (the whole predictive subsystem, the whole per-session observation subsystem and `evaluation_criterion_scores` were each created and then dropped inside the chain). The resulting schema is catalog-identical to what the nine migrations produced, bar one deliberate change: `quiz` and `rubrica` are gone from the assessment `kind` vocabulary in all three tables that carry it. Server code needed no change — nothing in Go validates or names those two kinds. **Two cascades were deliberately left undone**, both recorded as Open Questions: `seed/seed_demo_tenant.sql` writes both kinds and therefore no longer applies, and `yanai-ui` still offers both in two dropdowns. This file's `migrations/` Contents line, stale since the first squash, was corrected at the same time. See `migrations/SPEC.md` for the verification method and the full object-by-object account.
- 2026-08-29: Second purge pass. Fixed a live 500: `GET /profile` queried the dropped `risk_flags` table (see `internal/repo/SPEC.md`). Deleted the per-session observation subsystem whole (`migrations/00007`) — the flag catalog had no seed or provisioning path anywhere, and the free-text note had no writer in the UI. Deleted `yanai-schema-prompt.md`: it pointed readers at `yanai-views.html`, itself deleted from the repo, and is a single-use prompt nobody re-runs. Purged 13 more dead constant groups from `internal/domain`, the unused `progress` computation from the class dashboard, and `yanai-ui/src/lib/transcribe.ts`. Corrected a run of stale claims across this file, `README.md`, `DEPLOY.md`, `bruno/yanai-api.yaml` and several package SPEC.md files — a fixed "six screens" count, a Go 1.22 floor against an actual 1.26 module, a missing `go-chi/cors` dependency, an endpoint table missing five live routes, a worker "ticker" that never existed, and a migration number retired by the 2026-08-26 squash. See the SPEC.md of `internal/httpapi`, `internal/repo`, `internal/domain`, `internal/db`, `internal/media` and `migrations` for the per-package reasoning.
- 2026-08-29: Purge pass. Deleted the end-of-period SIAGIE report end to end (`internal/repo/siagie.go`, its handler and route), eight further routes no client called, and the retired AI note-summary feature. The lesson roster stopped carrying a per-student nivel de logro, trend and participation rating, and `session_observations.participation_level` was dropped in `00006`. `internal/domain` lost the constant blocks for subsystems with no Go code left. The Contents line for `migrations/` had also been stale since the squash. See the SPEC.md of `internal/httpapi`, `internal/repo`, `internal/domain` and `migrations` for the reasoning.
- 2026-08-27: Realigned grading with RVM 094-2020: criterios de evaluación per competencia are now a first-class surface (schema `00003`, `internal/repo/criteria.go`, `internal/httpapi/criteria.go`, and the criterios screen in `yanai-ui`), the weighted result was demoted to a labelled internal system, and everything predictive was removed — `internal/promotion` (with the repo's only test file), both risk job kinds, and the `risk_*` tables. `internal/grading` survives as the internal system's math.
- 2026-08-26: `seed/`'s add-on scripts were folded back into `seed_demo_tenant.sql`; Contents line updated. `migrations/` squashed its 18-file history into `00001_initial_schema.sql`.
- 2026-08-25: `seed/` now holds add-on scripts alongside the demo seed (`add_class_ingles_5to_a.sql`); the Contents line was widened to say so.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
