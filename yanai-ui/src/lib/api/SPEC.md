## Purpose
The wire layer: REST client, DTO types matching the server's JSON exactly, and mappers converting DTOs into the app's view models.

## Contents
- `client.ts` — `API_BASE` (from `PUBLIC_API_BASE_URL`, empty = same origin), `ApiError`, `apiGet`/`apiSend`/`apiUpload`, `fetchAudioBlob`, and `list()` normalizing the server's null empty lists. A `204 No Content` resolves as `undefined` rather than being parsed as JSON — the delete routes answer 204. Attaches `X-Tenant-ID`/`X-Actor-ID` from PUBLIC_ env on every request.
- `dto.ts` — wire types exactly as serialized: snake_case, UUID strings, RFC3339 timestamps, "YYYY-MM-DD" dates, null-for-empty-list; shared enums mirror `internal/domain/consts.go`.
- `mappers.ts` — DTO → app-type translation (dates, names, `toHomeCourses`, `toAppNotification`, …); the single place wire shapes are converted.
- `endpoints/` — one module per API area (see its SPEC.md).

## Inputs / Outputs
Consumes the Go API; produces typed promises for `lib/` orchestration modules.

## Conventions & Constraints
- DTOs mirror the server exactly — when a server response changes, update `dto.ts` + `mappers.ts` (cascade from `yanai-server/internal/httpapi`).
- `NivelLogro` is `'AD' | 'A' | 'B' | 'C'` and nothing else. Never widen it to a number or map it onto 0-20: the equivalence C 0-10 / B 11-13 / A 14-17 / AD 18-20 is Anexo 07 of RVM 094-2020, which expired for Secundaria on 1 March 2021.
- `CompetencyLevelDto.level === null` means "not developed this period", which is a valid state under 5.1.2.2 p.1. Render it as blank — never as C, and never as a zero. The same rule holds for a criterio with no level on a piece of evidence, and for a criterio absent from a grid row's `levels` map.
- `AssertCriterionLevelDto.assessment_id` is required. A criterio level always names the evidencia it was read from; the server refuses a body without one (`criterion_level_needs_evidence`).
- Conversion happens only in `mappers.ts`; components never touch DTOs.

## Change Log
- 2026-08-29: `dto.ts` and `mappers.ts` shed what no screen reads. Gone with the end-of-period report: `SiagieReportDto` and its three companions, and `toSiagieReport`. Gone with the lesson row's badges: `level_code`, `previous_level_code`, `trend` and `participation_level` on `RosterEntryDto`, plus `participation_level` on `ObservationPutDto`. Gone with the routes deleted server-side: `NoteSummaryDto`/`SummaryStatus` and `StudentGradesDto.summary`, `ClassSearchDto`, `SessionListDto`, `TranscriptionStatus`. Also dropped as never-read mirror fields: `AttemptDto.attempt_kind` (and `AttemptKind`), `AttendancePutDto.minutes_late`, `CompetencyLevelDto.level_id`/`subject_id`, `CriterionDto.sort_order`, `NotificationDto.dismissed_at`, `RosterVoiceNoteDto.transcription_status` — the server stopped sending that last one in the same change, so the DTO is still an exact mirror. `Trend` stays: `ComputedGradeDto` uses it. Cascade: `yanai-server/internal/repo`, `yanai-server/internal/httpapi`.
- 2026-08-28: Criterio levels moved to evidencia × criterio grain. `CriterionDto` lost its single `level`/`level_id` and gained `evidence` (`CriterionEvidenceDto[]`, the criterio's row across the period) plus `period_level` (the legacy period-grain judgement, read-only history). `CriterionRefDto` gained `level`, so an evidence row can render its pickers. `AssertCriterionLevelDto` gained a required `assessment_id` and lost `term_id` — the evidencia carries the periodo. Added the grid DTOs (`GridCriterionDto`, `GridStudentDto`, `AssessmentCriteriaGridDto`). `EvaluationDto` gained `counts_toward_internal` and `AssessmentCreateDto` an optional one; `MeDto.tenant` gained `uses_internal_grading`. Cascade: `yanai-server/internal/repo`.
- 2026-08-28: `request()` no longer parses a `204 No Content` body as JSON. It threw on every successful delete, so `deleteAssessment` and the pre-existing `deleteCriterion` both reported failure and skipped their refresh even though the server had done the work. Added `GradingComponentDto`/`GradingComponentsDto`; `AssessmentCreateDto` gained `student_id` and `criterion_ids`, and `EvaluationDto` gained `is_personal`. Cascade: `internal/repo/grades.go`.
- 2026-08-26: `mappers.ts` gained `toCompetencyLevel`/`toSiagieReport`, consumed by the grades screen's new competencias section and the new `class/[courseId]/siagie-report` route. Both view models reuse `Tier` from `lib/grades.ts` rather than the DTO layer's `NivelLogro` — same shape, one name on the app side.
- 2026-08-27: Added the criterio DTOs (`CriterionDto`, `CompetencyCriteriaDto`, `ClassCriteriaDto`, `CriterionCreateDto`, `AssertCriterionLevelDto`, `CriterionRefDto`) and removed what the norm does not support: `suggested_level` from `CompetencyLevelDto`, `weight` from `EvaluationDto`, the two `projected_*` fields from `ComputedGradeDto`, and `at_risk`/`stats.en_riesgo` from `ClassDashboardDto`. `EvaluationDto` gained `criteria` — which criterios that assessment evidences. `ComputedGradeDto` is now documented as the school's optional internal weighted system, never the record. Cascade: `internal/repo`.
- 2026-08-26: Added the competencia DTOs (`NivelLogro`, `CompetencyLevelDto`, `SiagieReportDto`, …) for the official MINEDU record.
- 2026-08-25: `EvaluationDto` gained `component_name` (cascade from `internal/repo/grades.go`); the grades screen labels its component sections from it instead of a hardcoded code→label map.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
