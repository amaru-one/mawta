## Purpose
Monorepo root for Yanai, a mobile-first assistant for secondary school teachers in Peru: a Go API (`yanai-server/`), a SvelteKit SPA (`yanai-ui/`), and deployment infrastructure (`deploy/`, `.github/`).

## Contents
- `CLAUDE.md` — project instructions: the mandatory SPEC protocol every session must follow.
- `DEPLOY.md` — step-by-step runbook for deploying to a single DigitalOcean VPS (Postgres + API + Caddy via Docker Compose) with a GitHub Actions pipeline; `[HUMAN]` marks manual steps.
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
- Generated/tool directories (`.svelte-kit/`, `node_modules/`, `.vscode/`, `.claude/`, `yanai-ui/build/`) and the empty `yanai-server/data/` carry no SPEC.md.

## Change Log
- 2026-08-29: Second purge pass. Fixed a live bug: `GET /profile` 500'd on any tenant with an active term because it queried `risk_flags`, dropped by `migrations/00003` — the "Alumnos en seguimiento" tile is gone with it, with no replacement. Deleted the whole per-session observation subsystem (`session_observations`, `session_observation_flags`, `behavior_flag_types`, `migrations/00007`): the flag catalog had no seed or provisioning path in any environment, so it could never raise a flag, and the free-text note had no writer in the UI. `yanai-views.html`, deleted from the working tree, is no longer treated as the product spec of record anywhere in the repo — the per-folder SPEC.md files are, and `yanai-schema-prompt.md` (which pointed at that file) was deleted too. Also purged 13 more dead constant groups in `internal/domain/consts.go`, the unused `progress` computation on the class dashboard, `lib/transcribe.ts`, and a pass of stale spec claims (a false "risk is grade-driven" note, a ticker that never existed, a migration number retired by the 2026-08-26 squash, and several screen-count/route-list mismatches). See `yanai-server/SPEC.md`, `internal/repo/SPEC.md`, `internal/httpapi/SPEC.md`, `internal/domain/SPEC.md`, `migrations/SPEC.md`, and `yanai-ui/src/lib/SPEC.md`.
- 2026-08-29: Purge pass across both apps, reflected here in `yanai-views.html`. Screen 07 (Reporte SIAGIE) was deleted with the route behind it — it was read-only over data screen 04 already owns, and the one thing only it could do, filing evidencia for the whole class, moved to the class dashboard. Screen 03's roster rows lost their participation dots, their per-row nivel de logro badge and the "A →" trend arrow, plus the `.part` CSS behind the dots; the section-average badge stays. Screen 04 lost the "Generar resumen" button and the AI summary card, whose endpoint had returned 501 since the job kind was retired. Also removed a pile of code with no reachable caller — eight API routes, `session_observations.participation_level` (migration `00006`) and assorted orphan functions. See `yanai-server/SPEC.md` and `yanai-ui/src/routes/SPEC.md`.
- 2026-08-27: Screen 04 in `yanai-views.html` was rebuilt to match the criterio-based model: the weighted "RESULTADO PARCIAL" hero and the "Rango posible al cierre" projection are gone, competencias lead with their criterios, "EVALUACIONES" became "EVIDENCIA" without weights, and the weighted grade appears only as a labelled "Sistema interno de la IE" card. See `yanai-server/SPEC.md` and `yanai-ui/src/routes/grades/[studentId]/SPEC.md`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
