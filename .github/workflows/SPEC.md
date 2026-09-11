## Purpose
GitHub Actions pipelines: CI checks on every PR/push, and production deploy on push to `main`.

## Contents
- `ci.yml` — two jobs: `server` (Go 1.26, `go vet` + `go build` in `yanai-server/`) and `ui` (Bun, `bun install --frozen-lockfile`, `bun run check`, `bun eslint .`, `bun run build` in `yanai-ui/`). Runs on pull_request and push to `main`.
- `deploy.yml` — on push to `main` (concurrency group `deploy-production`, no cancel-in-progress): builds the API image and pushes to GHCR (`ghcr.io/<owner>/yanai-api:latest` + `:sha`), builds the SPA with empty `PUBLIC_API_BASE_URL` (no auth-related build vars any more — see Change Log), then deploys to the VPS over SSH and smoke-tests it.

## Inputs / Outputs
Inputs: SSH credentials for the VPS (`SSH_KEY`, `SSH_HOST`, `SSH_USER`), `DOMAIN`, implicit `GITHUB_TOKEN` for GHCR. Outputs: GHCR image, SPA files on the VPS, restarted compose stack. See `DEPLOY.md` at the repo root for the full runbook and GHCR auth notes.

## Conventions & Constraints
- Deploy is single-environment (production) and serialized by the concurrency group.
- The SPA build has nothing tenant/actor-specific baked in any more — auth is a runtime session cookie, not a build artifact, so the same build works for any tenant.
- **The smoke test deliberately holds no real credential.** It asserts `/api/v1/me` answers `401` (no session), not that a login succeeds — CI must never carry a password capable of touching real school data, and a plain "the route is up and enforces auth" check is enough to catch a broken deploy.
- CI has no tests to run yet (no Go or UI test suite exists); vet/build/check/lint are the gate.

## Change Log
- 2026-09-11: Real authentication retired the two `PUBLIC_TENANT_ID`/`PUBLIC_ACTOR_ID` repo secrets — dropped from both the SPA build env and the smoke test, which now asserts `401` instead of sending them as headers. **The two secrets are dead and should be deleted from the repo's GitHub settings** (not done here — this file only covers what the workflow reads). Cascade: `deploy/docker-compose.prod.yml`, `DEPLOY.md`, `yanai-ui/.env.example`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
