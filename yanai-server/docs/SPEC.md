## Purpose
Developer documentation that doesn't belong in the README.

## Contents
- `postgres-setup.md` — runbook for the local dev database: `pgvector/pgvector:pg16` container named `yanai-pg` on port 55432 (extensions pgvector, btree_gist, pg_trgm), applying migrations, and running the seed.

## Inputs / Outputs
Consumed by humans and sessions setting up a dev environment; referenced by `README.md`, `bruno/yanai-api.yaml`, and `DEPLOY.md`.

## Conventions & Constraints
- Keep container name (`yanai-pg`), port (55432), and credentials in sync with `../.env`.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
