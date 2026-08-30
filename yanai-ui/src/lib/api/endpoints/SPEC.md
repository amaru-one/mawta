## Purpose
Typed wrappers over the API routes, one module per area, all built on `../client.ts`.

## Contents
- `home.ts` — `getMe`, `getHome(date?)`.
- `classes.ts` — `getClassDashboard`, `getGradingComponents`, `createAssessment` (omit `student_id` for the whole class, set it for one student), `deleteAssessment` (soft).
- `sessions.ts` — `getSession`, `startSession`, `putAttendance`, `markAllPresent`, `createVoiceNote`, save/discard.
- `grades.ts` — `getStudentGrades`, `createScore`, `correctScore`, `createPracticeScore`, `deletePracticeScore`.
- `notifications.ts` — `getNotifications` (cursor pagination via `before` = oldest created_at held), `markNotificationRead`, `markAllNotificationsRead`. The unread badge is derived client-side in `lib/stores.ts` from the loaded feed, so there is no count endpoint.
- `competencies.ts` — `getStudentCompetencies`, `assertCompetencyLevel`, `upsertConclusion`. The official MINEDU record, as opposed to `grades.ts`, which carries evidence (marks) and the optional internal weighted grade.
- `criteria.ts` — `getClassCriteria`, `createCriterion`, `deleteCriterion`, `assertCriterionLevel`, `getAssessmentCriteriaGrid`. The criterios a competencia is judged against, one student's level per criterio _per piece of evidence_, and the class-wide marking grid for one evidence. Evidence for the teacher's judgement; never rolled up into the competency level.
- `profile.ts` — `getProfile(termId?)`.

## Inputs / Outputs
Thin: DTO in/out, no mapping, no state. Routes must match `yanai-server/internal/httpapi/router.go` (cascade).

## Conventions & Constraints
- Keep these free of view-model logic — mapping belongs in `../mappers.ts`, orchestration in `lib/*.ts`.
- `assertCriterionLevel` always sends the `assessment_id` the level was read from. There is no call that records a criterio level for a period in the abstract: the norm values evidence _through_ the criterio (5.1.1.3 p.3), so the criterio is the ruler and never the thing marked.
- `getAssessmentCriteriaGrid` returns no mark and must not be extended to. The school's numeric system is the other reading of the same evidence and travels on `grades.ts`.
- `assertCompetencyLevel` always sends an explicit level, chosen by the teacher. There is no suggestion to accept: the level is a judgement of the period's evidence against the criterios (RVM 094-2020, 5.1.1.3 p.2-3), and the UI must never auto-assert one — not from criterio levels, not from marks.

## Change Log
- 2026-08-29: Deleted `getFlagTypes` and `putObservation` from `sessions.ts` — the per-session observation subsystem they wrote to (`session_observations`, `session_observation_flags`, `behavior_flag_types`) is gone; see `yanai-server/migrations/SPEC.md`. Cascade from `lib/components/RosterRow.svelte`, `lib/lesson.ts`.
- 2026-08-29: Deleted every wrapper whose route was removed server-side, all of which had no caller here either: `searchClasses`, `getClassSessions`, `completeSession`, `postTranscript`, `getUnreadCount`, `dismissNotification`, `requestSummary`, and `getSiagieReport` with the end-of-period report screen. Cascade from `yanai-server/internal/httpapi/router.go`.
- 2026-08-28: `criteria.ts` gained `getAssessmentCriteriaGrid`, and `assertCriterionLevel` now carries a required `assessment_id` (and no `term_id`).
- 2026-08-28: `classes.ts` gained `getGradingComponents` and `deleteAssessment`, and `createAssessment` now carries the evidence's scope and criterios.
- 2026-08-27: Added `criteria.ts`. `competencies.ts` doc comments rewritten: the endpoint no longer returns a suggested level, and `grades.ts` is evidence rather than "the computed suggestion".
- 2026-08-26: Added `competencies.ts` for the niveles de logro routes.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
