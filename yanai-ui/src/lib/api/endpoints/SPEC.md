## Purpose
Typed wrappers over the API routes, one module per area, all built on `../client.ts`.

## Contents
- `home.ts` — `getMe`, `getHome(date?)`, `searchClasses(q)`.
- `classes.ts` — `getClassDashboard`, `getClassSessions`, `createAssessment`.
- `sessions.ts` — `getSession`, `startSession`, `completeSession`, `putAttendance`, `markAllPresent`, `putObservation`, `createVoiceNote`, `postTranscript`, save/discard.
- `grades.ts` — `getStudentGrades`, `createScore`, `correctScore`, `createPracticeScore`, `deletePracticeScore`, `requestSummary`.
- `notifications.ts` — `getNotifications` (cursor pagination via `before` = oldest created_at held), `getUnreadCount`, `markNotificationRead`, `markAllNotificationsRead`, `dismissNotification`.
- `profile.ts` — `getProfile(termId?)`.

## Inputs / Outputs
Thin: DTO in/out, no mapping, no state. Routes must match `yanai-server/internal/httpapi/router.go` (cascade).

## Conventions & Constraints
- Keep these free of view-model logic — mapping belongs in `../mappers.ts`, orchestration in `lib/*.ts`.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
