# Mawta API

Python API powering the Mawta app on top of the Postgres schema in `migrations/`. Stack: Starlette
+ `psycopg` 3, hand-written SQL (no ORM), an in-process Postgres-backed job queue, forced
row-level security per tenant, Claude through the Anthropic SDK for the agents. It replaced the
former Go `mawta-server`; the HTTP contract, the database and the log format are unchanged.

## Prereqs

- Python 3.13 and [`uv`](https://docs.astral.sh/uv/)
- `ffmpeg` on the PATH (voice notes are transcoded to MP3 on upload)
- A local Postgres from `docs/local-postgres-setup.md` (container `mawta-pg`, migrations applied
  with `goose`). There is no seed any more — create an account with `useradd` (below).

## Quick start

```sh
uv sync
uv run mawta-api          # listens on HTTP_ADDR (default :8080)
curl localhost:8080/healthz
```

Config comes from the environment and `.env` — same variable names as before (`DATABASE_URL`,
`ADMIN_DATABASE_URL`, `HTTP_ADDR`, `CORS_ORIGINS`, `WORKER_*`, `ANTHROPIC_API_KEY`, `*_AGENT_MODEL`,
`SESSION_*`, `LOGIN_*`, `BCRYPT_COST`, `CHAT_TOKEN_*`, `TRANSCRIBE_*`, `STORAGE_DIR`, `LOG_LEVEL`,
`REQUEST_BODY_CAPTURE`). An empty variable counts as unset; an invalid value stops the boot
instead of silently using the default.

## Commands

| Command | What it does |
|---|---|
| `uv run mawta-api` | The HTTP server plus, when `WORKER_ENABLED`, the in-process worker |
| `uv run useradd -tenant <uuid> -username jquispe -email … -given-name … -family-name … -role teacher` | Create (or `-reset-password`) one account; needs `ADMIN_DATABASE_URL` |
| `uv run onboard -file colegio.json [-dry-run]` | Install a whole school; `-sync -modular <code> -grado 1S=1S` updates its curriculum |
| `uv run chatkey -kid k1` | Generate the Ed25519 key pair for the director's chat token |
| `uv run pytest` | The tests (database tests need `MAWTA_TEST_ADMIN_URL`, a superuser URL) |
| `uv run ruff check . && uv run ruff format --check .` | Lint |

In the container the same commands are on the PATH, e.g.
`docker compose run --rm --entrypoint useradd api …`; migrations run with
`docker compose run --rm --entrypoint /usr/local/bin/goose api up`.

## Logging

One JSON object per line on stdout with a stable `service` field, `mawta-server` (kept so the
Loki/Grafana dashboards keep working). `LOG_LEVEL` is `debug|info|warn|error` (default `info`).
Events: `http.request` (one per request, with `request_id`, `route` pattern, `status`,
`duration_ms`), `worker.job_started` / `worker.job_outcome`, `stt.usage`, `agent.usage`. No entry
contains passwords, tokens, cookies, API keys, request bodies (unless the opt-in
`REQUEST_BODY_CAPTURE` allowlist applies), audio, transcripts or student data.

## Layout

```
src/
  main.py settings.py web.py applog.py db.py errors.py     app factory, config, plumbing
  auth/ chattoken.py authz.py                               sessions, chat token, per-class guards
  repo/                                                     hand-written SQL, one module per area
  routes/                                                   HTTP handlers, one module per screen
  agent/ worker/ stt.py media.py                            agents, job queue, STT, ffmpeg
  onboarding/ curriculum/ cli/                              school installer, CNEB catalog, CLIs
tests/                                                      pytest, real Postgres, fixture.sql
```
