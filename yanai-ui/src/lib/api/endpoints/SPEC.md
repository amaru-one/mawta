## Purpose
Typed wrappers over the API routes, one module per area, all built on `../client.ts`.

## Contents
- `auth.ts` — `login(username, password)` (`POST /auth/login`, returns the same shape `getMe` does), `logout()` (`POST /auth/logout`, idempotent). The only two routes mounted outside session auth server-side — see `internal/httpapi/SPEC.md`.
- `home.ts` — `getMe`, `getHome(date?)`. `getMe` doubles as the session probe the root layout calls on mount — there is no separate endpoint for that.
- `classes.ts` — `getClassDashboard`, `getGradingComponents`, `createAssessment` (omit `student_id` for the whole class, set it for one student), `deleteAssessment` (soft).
- `sessions.ts` — `getSession`, `startSession`, `createVoiceNote`, save/discard.
- `grades.ts` — `getStudentGrades`, `createScore`, `correctScore`, `createPracticeScore`, `deletePracticeScore`.
- `notifications.ts` — `getNotifications` (cursor pagination via `before` = oldest created_at held), `markNotificationRead`, `markAllNotificationsRead`. The unread badge is derived client-side in `lib/stores.ts` from the loaded feed, so there is no count endpoint.
- `competencies.ts` — `getStudentCompetencies`, `assertCompetencyLevel`, `upsertConclusion`. The official MINEDU record, as opposed to `grades.ts`, which carries evidence (marks) and the optional internal weighted grade.
- `criteria.ts` — `getClassCriteria`, `createCriterion`, `deleteCriterion`. Authoring only: the criterios a competencia is read against, which a piece of evidencia is then tagged with. Nothing here records a level.
- `students.ts` — `getClassStudents` (the roster with each student's level in one competencia and its evidence count) and `getStudentEvidence` (that student's evidence for the period, narrowed to the competencia server-side). The two reads the evaluating screens are built on.
- `profile.ts` — `getProfile(termId?)`.

## Inputs / Outputs
Thin: DTO in/out, no mapping, no state. Routes must match `yanai-server/internal/httpapi/router.go` (cascade).

## Conventions & Constraints
- Keep these free of view-model logic — mapping belongs in `../mappers.ts`, orchestration in `lib/*.ts`.
- **The two attendance routes are live server-side and deliberately have no wrapper here.** `PUT /sessions/{id}/attendance/{studentID}` and `POST /sessions/{id}/attendance/mark-all-present` are unchanged in `router.go`; their absence from `sessions.ts` since 2026-09-02 is a product decision, not drift from the router, and the usual "the wrapper is missing, the route must be gone" reasoning does not apply.
- `getSession` takes an optional `q` that filters the roster server-side. It is intentionally unused: the lesson screen searches the roster already in its store, which answers between keystrokes.
- **No call records a criterio level, and no wrapper for one should be added back.** There is no route to call any more either — `criterion-levels` and `criteria-grid` are gone server-side. The criterio is the ruler and never the thing marked (RVM 094-2020, 5.1.1.3 p.3); the only level this layer writes is `assertCompetencyLevel`.
- `assertCompetencyLevel` always sends an explicit level, chosen by the teacher. There is no suggestion to accept: the level is a judgement of the period's evidence against the criterios (RVM 094-2020, 5.1.1.3 p.2-3), and the UI must never auto-assert one — not from criterio levels, not from marks.

## Open Questions
- None.
