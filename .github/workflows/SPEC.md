## Purpose
GitHub Actions pipelines: CI checks on every PR/push, and production deploy on push to `main`.

## Contents
- `ci.yml` — two jobs: `server` (Go 1.26, `go vet` + `go build` in `yanai-server/`) and `ui` (Bun, `bun install --frozen-lockfile`, `bun run check`, `bun eslint .`, `bun run build` in `yanai-ui/`). Runs on pull_request and push to `main`.
- `deploy.yml` — on push to `main` (concurrency group `deploy-production`, no cancel-in-progress): builds the API image and pushes to GHCR (`ghcr.io/<owner>/yanai-api:latest` + `:sha`), builds the SPA with baked `PUBLIC_TENANT_ID`/`PUBLIC_ACTOR_ID` secrets and empty `PUBLIC_API_BASE_URL`, then deploys to the VPS over SSH.

## Inputs / Outputs
Inputs: repo secrets — `PUBLIC_TENANT_ID`, `PUBLIC_ACTOR_ID`, SSH credentials for the VPS, implicit `GITHUB_TOKEN` for GHCR. Outputs: GHCR image, SPA files on the VPS, restarted compose stack. See `DEPLOY.md` at the repo root for the full runbook and GHCR auth notes.

## Conventions & Constraints
- Deploy is single-environment (production) and serialized by the concurrency group.
- The SPA build bakes dev-auth headers in at build time — changing tenant/actor requires a rebuild.
- CI has no tests to run yet (no Go or UI test suite exists); vet/build/check/lint are the gate.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
