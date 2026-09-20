## Purpose
GitHub Actions pipelines: CI checks on every PR/push, and production deploy on push to `main`.

## Contents
- `ci.yml` — two jobs: `server` (Go 1.26 in `yanai-server/`: `go vet`, `go build`, then `go test ./... -count=1 -race -shuffle=on` against a `postgres:16` service container, with ffmpeg installed for the voice-note path) and `ui` (Bun, `bun install --frozen-lockfile`, `bun run check`, `bun eslint .`, `bun run build` in `yanai-ui/`). Runs on pull_request and push to `main`.
- `deploy.yml` — on push to `main` (concurrency group `deploy-production`, no cancel-in-progress): builds the API image and pushes to GHCR (`ghcr.io/<owner>/yanai-api:latest` + `:sha`), builds the SPA with empty `PUBLIC_API_BASE_URL` (no auth-related build vars any more), then deploys to the VPS over SSH and smoke-tests it.

## Inputs / Outputs
Inputs: SSH credentials for the VPS (`SSH_KEY`, `SSH_HOST`, `SSH_USER`), `DOMAIN`, implicit `GITHUB_TOKEN` for GHCR. Outputs: GHCR image, SPA files on the VPS, restarted compose stack. See `DEPLOY.md` at the repo root for the full runbook and GHCR auth notes.

## Conventions & Constraints
- Deploy is single-environment (production) and serialized by the concurrency group.
- The SPA build has nothing tenant/actor-specific baked in any more — auth is a runtime session cookie, not a build artifact, so the same build works for any tenant.
- **The smoke test deliberately holds no real credential.** It asserts `/api/v1/me` answers `401` (no session), not that a login succeeds — CI must never carry a password capable of touching real school data, and a plain "the route is up and enforces auth" check is enough to catch a broken deploy.
- **The server job must always set `YANAI_TEST_ADMIN_URL`.** The database tests skip without it, and a skipped run prints `ok` just like a passing one — so leaving it unset would let a change that breaks every query merge green. The tests create and drop their own database inside the service container; they never touch anything that outlives the job.
- `-shuffle=on` is deliberate: the suite shares one database per package, and it has already caught an order-dependent assertion that passed in file order.
- There is still no UI test suite; `check`/`eslint`/`build` remain the gate there.

## Open Questions
- None.
