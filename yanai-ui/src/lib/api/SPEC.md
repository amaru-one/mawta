## Purpose
The wire layer: REST client, DTO types matching the server's JSON exactly, and mappers converting DTOs into the app's view models.

## Contents
- `client.ts` — `API_BASE` (from `PUBLIC_API_BASE_URL`, empty = same origin), `ApiError`, `apiGet`/`apiSend`/`apiUpload`, `fetchAudioBlob`, and `list()` normalizing the server's null empty lists. Attaches `X-Tenant-ID`/`X-Actor-ID` from PUBLIC_ env on every request.
- `dto.ts` — wire types exactly as serialized: snake_case, UUID strings, RFC3339 timestamps, "YYYY-MM-DD" dates, null-for-empty-list; shared enums mirror `internal/domain/consts.go`.
- `mappers.ts` — DTO → app-type translation (dates, names, `toHomeCourses`, `toAppNotification`, …); the single place wire shapes are converted.
- `endpoints/` — one module per API area (see its SPEC.md).

## Inputs / Outputs
Consumes the Go API; produces typed promises for `lib/` orchestration modules.

## Conventions & Constraints
- DTOs mirror the server exactly — when a server response changes, update `dto.ts` + `mappers.ts` (cascade from `yanai-server/internal/httpapi`).
- Conversion happens only in `mappers.ts`; components never touch DTOs.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
