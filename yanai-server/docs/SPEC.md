## Purpose
Developer documentation that doesn't belong in the README.

## Contents
- `postgres-setup.md` — runbook for the local dev database: `pgvector/pgvector:pg16` container named `yanai-pg` on port 55432 (extensions pgvector, btree_gist, pg_trgm), applying migrations, running the seed, and the two reset paths (drop/recreate the database; rebuild the container).

## Inputs / Outputs
Consumed by humans and sessions setting up a dev environment; referenced by `README.md`, `bruno/yanai-api.yaml`, and `DEPLOY.md`.

## Conventions & Constraints
- Keep container name (`yanai-pg`), port (55432), and credentials in sync with `../.env`.

## Change Log
- 2026-08-29: `postgres-setup.md` still described the seed as "all four dataset blocks (Inglés, Historia, Arte)" — Inglés and Historia were dropped from the seed on 2026-08-26, leaving two blocks (base tenant + Arte). Corrected.
- 2026-08-26: Both reset recipes collapsed back to a single `seed_demo_tenant.sql` apply — `seed/` consolidated its four scripts (base tenant + three add-ons) into that one file, so there is nothing else to re-apply after it.
- 2026-08-25: Reset recipes gained `seed/add_class_arte_3ro_a.sql` (same reasoning as the other add-ons: they are part of the dataset).
- 2026-08-25: Both reset recipes now re-apply `seed/add_class_ingles_5to_a.sql` and `seed/add_class_historia_4to_a.sql` after the demo seed. The add-ons are part of the dataset, so replaying only `seed_demo_tenant.sql` silently rebuilt a database missing two classes.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
