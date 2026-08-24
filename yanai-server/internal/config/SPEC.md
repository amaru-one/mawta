## Purpose
Loads runtime configuration from the environment (plus `.env` in dev via godotenv).

## Contents
- `config.go` — `Config` struct and `Load()`, with helpers `getenv`/`getbool`/`getint`/`splitcsv`. Keys include `DATABASE_URL`, `HTTP_ADDR`, `LOG_LEVEL`, `CORS_ORIGINS`, `STORAGE_DIR`, `WORKER_ENABLED` (default true), `WORKER_CONCURRENCY` (default 2), `WORKER_QUEUE` (default "default").

## Inputs / Outputs
Inputs: process env and optional `.env`. Output: one immutable `Config` consumed by `cmd/api`, `httpapi`, and `worker`.

## Conventions & Constraints
- Every key has a sane dev default; production overrides via compose env.
- New config goes here with a default — nothing else reads `os.Getenv` directly.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
