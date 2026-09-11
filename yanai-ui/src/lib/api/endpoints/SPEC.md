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

## Change Log
- 2026-09-11: Added `auth.ts` for real authentication. Cascade: `lib/api/client.ts`, `lib/stores.ts`, `routes/+layout.svelte`, `routes/login/` (new), `routes/profile/`.
- 2026-09-04: Added `students.ts` — `getClassStudents` and `getStudentEvidence`, the two reads the evaluating screens are built on. `getClassCriteria` dropped its `studentId` parameter. The two criterio-level wrappers deleted this morning are now gone server-side too, so the note about them being untouched no longer applies.
- 2026-09-04: Deleted `assertCriterionLevel` and `getAssessmentCriteriaGrid` from `criteria.ts`, which is now authoring-only. Criterio grading is gone from the product: what is evaluated is the competencia, and a criterio is a tag on evidence. **Both routes are untouched server-side for now** — same situation as the attendance wrappers below, and Phase 2 deletes them properly. Cascade from `lib/api/dto.ts`, `routes/`.
- 2026-09-02: Deleted `putAttendance` and `markAllPresent` from `sessions.ts`. Both lost their only caller when the lesson screen became a recording screen and attendance left the app. **Their routes are untouched server-side** — see the new Conventions note, which exists so a later purge pass does not read the missing wrappers as evidence that the routes are dead. Cascade from `lib/lesson.ts`, `lib/api/dto.ts`.
- 2026-08-29: Deleted `getFlagTypes` and `putObservation` from `sessions.ts` — the per-session observation subsystem they wrote to (`session_observations`, `session_observation_flags`, `behavior_flag_types`) is gone; see `yanai-server/migrations/SPEC.md`. Cascade from `lib/components/RosterRow.svelte`, `lib/lesson.ts`.
- 2026-08-29: Deleted every wrapper whose route was removed server-side, all of which had no caller here either: `searchClasses`, `getClassSessions`, `completeSession`, `postTranscript`, `getUnreadCount`, `dismissNotification`, `requestSummary`, and `getSiagieReport` with the end-of-period report screen. Cascade from `yanai-server/internal/httpapi/router.go`.
- 2026-08-28: `criteria.ts` gained `getAssessmentCriteriaGrid`, and `assertCriterionLevel` now carries a required `assessment_id` (and no `term_id`).
- 2026-08-28: `classes.ts` gained `getGradingComponents` and `deleteAssessment`, and `createAssessment` now carries the evidence's scope and criterios.
- 2026-08-27: Added `criteria.ts`. `competencies.ts` doc comments rewritten: the endpoint no longer returns a suggested level, and `grades.ts` is evidence rather than "the computed suggestion".
- 2026-08-26: Added `competencies.ts` for the niveles de logro routes.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
