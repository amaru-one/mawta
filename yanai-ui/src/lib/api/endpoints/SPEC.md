## Purpose
Typed wrappers over the API routes, one module per area, all built on `../client.ts`.

## Contents
- `home.ts` — `getMe`, `getHome(date?)`, `searchClasses(q)`.
- `classes.ts` — `getClassDashboard`, `getClassSessions`, `createAssessment`.
- `sessions.ts` — `getSession`, `startSession`, `completeSession`, `putAttendance`, `markAllPresent`, `putObservation`, `createVoiceNote`, `postTranscript`, save/discard.
- `grades.ts` — `getStudentGrades`, `createScore`, `correctScore`, `createPracticeScore`, `deletePracticeScore`, `requestSummary`.
- `notifications.ts` — `getNotifications` (cursor pagination via `before` = oldest created_at held), `getUnreadCount`, `markNotificationRead`, `markAllNotificationsRead`, `dismissNotification`.
- `competencies.ts` — `getStudentCompetencies`, `assertCompetencyLevel`, `upsertConclusion`, `getSiagieReport`. The official MINEDU record, as opposed to `grades.ts`, which carries evidence (marks) and the optional internal weighted grade.
- `criteria.ts` — `getClassCriteria`, `createCriterion`, `deleteCriterion`, `assertCriterionLevel`. The criterios a competencia is judged against, and one student's level per criterio per periodo. Evidence for the teacher's judgement; never rolled up into the competency level.
- `profile.ts` — `getProfile(termId?)`.

## Inputs / Outputs
Thin: DTO in/out, no mapping, no state. Routes must match `yanai-server/internal/httpapi/router.go` (cascade).

## Conventions & Constraints
- Keep these free of view-model logic — mapping belongs in `../mappers.ts`, orchestration in `lib/*.ts`.
- `assertCompetencyLevel` always sends an explicit level, chosen by the teacher. There is no suggestion to accept: the level is a judgement of the period's evidence against the criterios (RVM 094-2020, 5.1.1.3 p.2-3), and the UI must never auto-assert one — not from criterio levels, not from marks.

## Change Log
- 2026-08-27: Added `criteria.ts`. `competencies.ts` doc comments rewritten: the endpoint no longer returns a suggested level, and `grades.ts` is evidence rather than "the computed suggestion".
- 2026-08-26: Added `competencies.ts` for the niveles de logro routes.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
