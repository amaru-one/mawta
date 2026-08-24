## Purpose
Importable API collection for manual testing with the Bruno client.

## Contents
- `yanai-api.yaml` — OpenAPI 3.0.3 spec of the whole API, tagged into folders (00 Health & Me … 06 Perfil), with every header/path/query/body example pre-filled for the seeded demo tenant (Janice Quispe's actor id).

## Inputs / Outputs
Import into Bruno (Import Collection → OpenAPI Spec). Targets `go run ./cmd/api` against the seeded local Postgres.

## Conventions & Constraints
- This file documents, it does not drive codegen. When routes change in `internal/httpapi/router.go`, update this spec too (cascade).
- Examples embed seed-stable UUIDs; a reseed keeps them valid, hand-edited data may not.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
