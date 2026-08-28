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
- `NivelLogro` is `'AD' | 'A' | 'B' | 'C'` and nothing else. Never widen it to a number or map it onto 0-20: the equivalence C 0-10 / B 11-13 / A 14-17 / AD 18-20 is Anexo 07 of RVM 094-2020, which expired for Secundaria on 1 March 2021.
- `CompetencyLevelDto.level === null` means "not developed this period", which is a valid state under 5.1.2.2 p.1. Render it as blank — never as C, and never as a zero.
- Conversion happens only in `mappers.ts`; components never touch DTOs.

## Change Log
- 2026-08-26: `mappers.ts` gained `toCompetencyLevel`/`toSiagieReport`, consumed by the grades screen's new competencias section and the new `class/[courseId]/siagie-report` route. Both view models reuse `Tier` from `lib/grades.ts` rather than the DTO layer's `NivelLogro` — same shape, one name on the app side.
- 2026-08-27: Added the criterio DTOs (`CriterionDto`, `CompetencyCriteriaDto`, `ClassCriteriaDto`, `CriterionCreateDto`, `AssertCriterionLevelDto`, `CriterionRefDto`) and removed what the norm does not support: `suggested_level` from `CompetencyLevelDto`, `weight` from `EvaluationDto`, the two `projected_*` fields from `ComputedGradeDto`, and `at_risk`/`stats.en_riesgo` from `ClassDashboardDto`. `EvaluationDto` gained `criteria` — which criterios that assessment evidences. `ComputedGradeDto` is now documented as the school's optional internal weighted system, never the record. Cascade: `internal/repo`.
- 2026-08-26: Added the competencia DTOs (`NivelLogro`, `CompetencyLevelDto`, `SiagieReportDto`, …) for the official MINEDU record.
- 2026-08-25: `EvaluationDto` gained `component_name` (cascade from `internal/repo/grades.go`); the grades screen labels its component sections from it instead of a hardcoded code→label map.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
