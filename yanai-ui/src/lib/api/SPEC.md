## Purpose
The wire layer: REST client, DTO types matching the server's JSON exactly, and mappers converting DTOs into the app's view models.

## Contents
- `client.ts` — `API_BASE` (from `PUBLIC_API_BASE_URL`, empty = same origin), `ApiError`, `apiGet`/`apiSend`/`apiUpload`, `fetchAudioBlob`, `list()` normalizing the server's null empty lists, and `setUnauthorizedHandler` (called once from the root layout). A `204 No Content` resolves as `undefined` rather than being parsed as JSON — the delete routes answer 204. Every request carries `credentials: 'include'` so the `yanai_session` HttpOnly cookie rides along; a `401` fires the unauthorized handler **unless the path starts with `/auth/`** — a wrong password is a 401 on `POST /auth/login` itself, and without that exclusion a failed login would redirect to `/login` and swallow the error the form needs to show.
- `dto.ts` — wire types exactly as serialized: snake_case, UUID strings, RFC3339 timestamps, "YYYY-MM-DD" dates, null-for-empty-list; shared enums mirror `internal/domain/consts.go`. `Role` (`'teacher' | 'student' | 'supervisor' | 'admin'`) mirrors `domain.Role*`; `MeDto` gained `role`.
- `mappers.ts` — DTO → app-type translation (dates, names, `toAppNotification`, …); the single place wire shapes are converted. Note that not every screen maps: the class dashboard and Home both render their DTO directly with local formatters, and reuse only the primitives here (`parseDateOnly`, `formatTimeHHMM`).
- `endpoints/` — one module per API area (see its SPEC.md).

## Inputs / Outputs
Consumes the Go API; produces typed promises for `lib/` orchestration modules.

## Conventions & Constraints
- DTOs mirror the server exactly — when a server response changes, update `dto.ts` + `mappers.ts` (cascade from `yanai-server/internal/httpapi`). One deliberate exception: a response field the server still sends but no screen has ever read is left off the DTO rather than kept as documentation of the wire shape — `dto.ts` types the wire contract this app actually uses, not the full JSON. Check the Go response struct, not just this file, before assuming a field doesn't exist server-side.
- `NivelLogro` is `'AD' | 'A' | 'B' | 'C'` and nothing else. Never widen it to a number or map it onto 0-20: the equivalence C 0-10 / B 11-13 / A 14-17 / AD 18-20 is Anexo 07 of RVM 094-2020, which expired for Secundaria on 1 March 2021.
- `CompetencyLevelDto.level === null` means "not developed this period", which is a valid state under 5.1.2.2 p.1. Render it as blank or a dash — never as C, and never as a zero.
- **There is no criterio level in the wire layer, and none should be added.** `CriterionDto` and `CriterionRefDto` carry text only: a criterio is what a piece of evidencia is tagged with, not something that is graded. The only level type the app writes is `AssertCompetencyLevelDto`.
- Conversion happens only in `mappers.ts`; components never touch DTOs.

## Open Questions
- None.
