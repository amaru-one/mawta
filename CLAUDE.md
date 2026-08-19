# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This is a single monorepo (`/Users/amaru/yanai`) containing two subprojects with independent toolchains:

- `yanai-server/` — Go API
- `yanai-ui/` — SvelteKit frontend, consuming `yanai-server`'s API over `/api/v1/*`

`yanai-ui` was previously its own separate git repo (`github.com/06amaru/yanay-ui`); its history was merged in via `git subtree` and that repo is now just an archive — do not treat it as a source of truth. Each subproject has its own toolchain; work inside the relevant one rather than mixing commands.

## yanai-server (Go)

- Run: `go run ./cmd/api` (reads `.env`, health check at `/healthz`)
- No test suite exists yet (no `*_test.go` files); no lint config beyond standard `go vet`/`gofmt`.
- Migrations use **goose**, not a built-in Go tool: `goose -dir migrations postgres "$DATABASE_URL" up`
- Postgres runs on **port 55432** (not 5432) to avoid clashing with a local install — see `yanai-server/docs/postgres-setup.md` for the required extensions (pgvector, btree_gist, pg_trgm).
- Every table has **FORCE**d row-level security. The app connects as the non-owner `yanai_app` role and must `set local app.tenant_id`/`app.actor_id` per transaction — if that's missing, queries silently return zero rows rather than erroring.
- `scores` and `computed_grades` are append-only: never `UPDATE` them; corrections stamp `superseded_at` and insert a new row. Hard `DELETE` is trigger-blocked on every table except `jobs`.
- Seed data (`yanai-server/seed/seed_demo_tenant.sql`) is run directly with `psql -f`, not through goose — see `yanai-server/seed/README.md` for the rules (e.g. grading-scheme component weights must sum to exactly 1).
- Routes require dev auth headers `X-Tenant-ID` and `X-Actor-ID` — there's no real auth yet.

## yanai-ui (SvelteKit)

- Package manager is **Bun**, not npm/yarn/pnpm — use `bun install`, `bun dev`, `bun run build`.
- Type check: `bun run check` (runs `svelte-kit sync` + `svelte-check`).
- Lint/format: `bun eslint .` / `bun prettier --write .` (no npm scripts for these — see `.claude/skills/verify` and `.claude/skills/format` in this subproject).
- Prettier is configured non-default: tabs (not spaces), single quotes, 100-char print width — let Prettier handle formatting rather than hand-formatting.
- No test framework is set up.
- Talks to `yanai-server` via `src/lib/api/` (typed fetch client, DTOs, mappers) — dev auth headers come from `PUBLIC_TENANT_ID`/`PUBLIC_ACTOR_ID` env vars (see `.env.example`). No IndexedDB, no mock data — every screen reads and writes through the API.
- SPA build via `adapter-static` (`fallback: 'index.html'`); the Vite dev server proxies `/api` and `/healthz` to `localhost:8080` so dev is same-origin too.

## Deployment

See `DEPLOY.md` at the repo root for the full runbook (single VPS, Docker Compose, Caddy, GitHub Actions CI/CD).
