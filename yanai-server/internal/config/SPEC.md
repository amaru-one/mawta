## Purpose
Loads runtime configuration from the environment (plus `.env` in dev via godotenv).

## Contents
- `config.go` — `Config` struct and `Load()`, with helpers `getenv`/`getbool`/`getint`/`getdur`/`splitcsv`. Keys include `DATABASE_URL` (required; the app's own connection, as the non-owner `yanai_app` role), `ADMIN_DATABASE_URL` (optional here — a connection with real ownership/DDL rights or the pre-tenant bypass `cmd/useradd` needs; `cmd/api` never reads it, `cmd/useradd` requires it and fails fast if it's empty), `HTTP_ADDR`, `LOG_LEVEL`, `CORS_ORIGINS`, `STORAGE_DIR`, `WORKER_ENABLED` (default true), `WORKER_CONCURRENCY` (default 2), `WORKER_QUEUE` (default "default"), `OPENAI_API_KEY` (default `""`), `OPENAI_TRANSCRIBE_MODEL` (default `"gpt-4o-mini-transcribe"`), plus the session/auth keys below.

### Session/auth keys (added for real authentication)
| Key | Default | Note |
|---|---|---|
| `SESSION_COOKIE_NAME` | `yanai_session` | |
| `SESSION_COOKIE_SECURE` | `true` | Fails closed on a forgotten env var. Dev sets `false` in `.env` — Safari refuses `Secure` over plain `http://localhost`. |
| `SESSION_TTL` | `720h` | Absolute session lifetime, never extended. |
| `SESSION_IDLE_TIMEOUT` | `336h` | Checked in Go against `user_sessions.last_seen_at`, not a DB-side expiry. |
| `LOGIN_MAX_FAILURES` | `8` | Consecutive failures before a lockout. |
| `LOGIN_LOCKOUT` | `15m` | |
| `BCRYPT_COST` | `12` | Lets `cmd/useradd` run with a lower cost in tests if ever needed. |

## Inputs / Outputs
Inputs: process env and optional `.env`. Output: one immutable `Config` consumed by `cmd/api`, `cmd/useradd`, `httpapi`, and `worker`.

## Conventions & Constraints
- Every key has a sane dev default; production overrides via compose env.
- New config goes here with a default — nothing else reads `os.Getenv` directly.
- `Load()` refuses to start if `SESSION_COOKIE_SECURE` is true and any `CORS_ORIGINS` entry is `"*"` — `AllowCredentials` with a wildcard origin is rejected by every browser anyway, and is the classic footgun combined with `Secure` cookies.

## Open Questions
- None.
