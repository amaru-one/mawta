## Purpose
Demo data and the runbook for hand-onboarding real data (school, section, students, teachers, classes, grading scheme).

## Contents
- `seed_demo_tenant.sql` — the worked example: full demo tenant (currently Math + English classes) applied with `psql -f` after migrations. Survives/expects reseeds; hard deletes allowed for reseeding.
- `README.md` — the onboarding runbook; every pattern is lifted from the seed script. Documents the big gotcha: FORCE RLS applies even to the table owner, so scripts must set the session tenant GUCs.

## Inputs / Outputs
Requires migrations applied first. Produces the demo tenant whose tenant/actor UUIDs are baked into `bruno/yanai-api.yaml`, the deployed SPA build (GitHub secrets), and the server README — keep those stable across reseeds (cascade if they change).

## Conventions & Constraints
- Not migrations: run manually with `psql "$DATABASE_URL" -f`.
- In production the directory is bind-mounted read-only into the postgres container at `/seed`.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
