## Purpose
Production runtime configuration for the single-VPS deployment: three containers (Postgres, API, Caddy) plus the static SPA.

## Contents
- `docker-compose.prod.yml` — the production stack. `postgres` (pgvector/pgvector:pg16, volume `pgdata` — no seed mount), `api` (image `${API_IMAGE}`, worker enabled, `SESSION_COOKIE_SECURE: 'true'`, audio at `/srv/yanai/audio` → `/data/audio`, goose env vars set so `docker compose run --rm --entrypoint goose api up` migrates with zero args — the distroless image has no shell; `docker compose run --rm --entrypoint useradd api ...` creates the first account, see `../yanai-server/cmd/useradd/SPEC.md`), `caddy` (caddy:2-alpine, ports 80/443 + 443/udp, serves the SPA and proxies the API — Caddy must forward `Cookie`/`Set-Cookie` untouched, which its default reverse-proxy behavior already does).
- `Caddyfile` — `{$DOMAIN}` site: `/api/*` and `/healthz` reverse-proxy to `api:8080`; everything else served from `/srv/ui` with `try_files {path} /index.html` (SPA fallback); gzip on.

## Inputs / Outputs
Inputs: `/srv/yanai/.env` on the VPS (`POSTGRES_PASSWORD`, `DOMAIN`, `API_IMAGE`); the built SPA at the Caddy `/srv/ui` mount; the GHCR API image. Outputs: the live HTTPS site — same origin for SPA and API, so no CORS in production.

## Conventions & Constraints
- Run from `/srv/yanai` with `docker compose --env-file /srv/yanai/.env -f docker-compose.prod.yml up -d` (see `../DEPLOY.md`).
- Single-node by design: audio on local disk, worker in-process. Do not split into multiple API instances without rethinking both.
- Migrations run via the goose entrypoint trick documented in the compose file comments.

## Open Questions
- None.
