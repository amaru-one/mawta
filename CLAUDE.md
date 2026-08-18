# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This directory holds two independent, separately-run projects:

- `yanai-server/` — Go API (not a git repo)
- `yanai-ui/` — SvelteKit frontend (its own git repo)

`yanai-ui` is meant to eventually consume `yanai-server`'s API, but that wiring isn't done yet — the UI is currently IndexedDB-only. Each subproject has its own toolchain; work inside the relevant one rather than mixing commands.

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
- The app is mid-redesign (working tree has uncommitted component/route changes); don't assume `yanai-ui/README.md` or its committed history reflect the current UI.
