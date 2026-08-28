## Purpose
Monorepo root for Yanai, a mobile-first assistant for secondary school teachers in Peru: a Go API (`yanai-server/`), a SvelteKit SPA (`yanai-ui/`), and deployment infrastructure (`deploy/`, `.github/`).

## Contents
- `CLAUDE.md` — project instructions: the mandatory SPEC protocol every session must follow.
- `DEPLOY.md` — step-by-step runbook for deploying to a single DigitalOcean VPS (Postgres + API + Caddy via Docker Compose) with a GitHub Actions pipeline; `[HUMAN]` marks manual steps.
- `yanai-views.html` — static gallery of the app screens (Home, Class dashboard, Lesson/attendance, Student grades, Notifications, Profile, SIAGIE report); the authoritative product spec the schema and API were derived from. Screen 04 now leads with the niveles de logro and their criterios: keep it in step with `yanai-ui`, or it stops being authoritative.
- `.gitignore` — root ignore rules.
- `yanai-server/` — Go API, migrations, seed data (see its SPEC.md).
- `yanai-ui/` — SvelteKit SPA (see its SPEC.md).
- `deploy/` — production Caddyfile and docker-compose (see its SPEC.md).
- `.github/workflows/` — CI and deploy pipelines (see its SPEC.md).
- `.claude/` — Claude Code local settings (tool config, no spec).

## Inputs / Outputs
Consumes nothing; produces the deployed app. `DEPLOY.md` assumes GitHub repo + GHCR + a VPS at `/srv/yanai`.

## Conventions & Constraints
- SPEC protocol in `CLAUDE.md` is mandatory: per-folder SPEC.md is source of truth, updated in the same turn as any change; stop if a change contradicts a spec.
- No real authentication yet — the deployed app must only ever hold the seeded demo tenant, never real student data.
- Generated/tool directories (`.svelte-kit/`, `node_modules/`, `.vscode/`, `.claude/`) and the empty `yanai-server/data/` carry no SPEC.md.

## Change Log
- 2026-08-27: Screen 04 in `yanai-views.html` was rebuilt to match the criterio-based model: the weighted "RESULTADO PARCIAL" hero and the "Rango posible al cierre" projection are gone, competencias lead with their criterios, "EVALUACIONES" became "EVIDENCIA" without weights, and the weighted grade appears only as a labelled "Sistema interno de la IE" card. See `yanai-server/SPEC.md` and `yanai-ui/src/routes/grades/[studentId]/SPEC.md`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
