## Purpose
Shared application logic: view-model types, Svelte stores, per-screen orchestration modules, and browser-capability helpers. Wire concerns live in `api/`; presentational pieces in `components/`.

## Contents
- `types.ts` — app-side (camelCase) view models: `Course`, `Student`, `Session`, `Entry`, `CompetencyLevel`, `CompetencyIndexItem`, etc. Wire shapes live in `api/dto.ts`; mappers translate. `CompetencyIndexItem` is a component prop shape rather than a mapped view model — it lives here because a Svelte component cannot export a type from its instance script.
- `stores.ts` — writable stores: `session` (`SessionState`: `'unknown' | 'anonymous' | { status: 'authenticated', role }`, populated by the root layout's `GET /me` probe — `'unknown'` is what stops a flash of app content before a redirect to `/login`), `currentCourse`, `currentSession`, `students`, `entries`, `notes`, `notifications`, `teacher`, `canGoBack`, `usesInternalGrading`, derived `unreadNotificationCount`; `entryKey(sessionId, studentId)` builds the natural key `entries`/`notes` are keyed by. `usesInternalGrading` mirrors `GET /me`'s `tenant.uses_internal_grading` — whether the school runs its own weighted numeric system (D.S. 009-2006-ED art. 37.4.f). It defaults to true so a screen rendered before `/me` resolves looks like the historical app, and it gates mark inputs and the internal-grade card only: niveles de logro never depend on it, since the official record never comes from a number either way. `canGoBack` is false until the SPA makes its first client-side navigation; `TopBar`'s `useHistory` back arrow reads it to decide between `history.back()` and its fallback href.
- `lesson.ts` — lesson-screen orchestration: loads the session roster and owns the voice-note mutations. Optimistic: store updates synchronously, API call in background, revert + error toast on rejection — autosave, no submit button. **Attendance is no longer part of this module** — `setAttendance`, `anyUnmarked` and `markAllPresent` went on 2026-09-02 with the screen that called them, taking the `patchEntry`/`restoreEntry`/`runMutation` trio, which existed only for the attendance PUT. Note that `addNote` early-returns unless `entries` already holds the student's key, so `loadSession` must keep populating the roster stores even for a screen that renders no list.
- `notifications.ts` — notification feed logic backed by GET /notifications; `aiGenerated` splits alerts (accent) from reminders (neutral).
- `grades.ts` — MINEDU achievement-level vocabulary (`Tier` AD/A/B/C); all grade math is server-side, the client renders codes. `Tier` doubles as the app-side type for `types.ts`'s `CompetencyLevel.level` — no separate `NivelLogro`-shaped app type.
- `recorder.ts` — press-and-hold MediaRecorder voice capture; mic stream kept warm after first grant; blob decode and duration formatting helpers. Exports `MAX_RECORD_SEC` (60) — a recording fact, not a view one, because the server enforces the same number and both the control that auto-stops at the cap and the screen that counts down to it have to agree with it.
- `toast.ts` — toast store with optional undo. `haptics.ts` — optional vibration feedback. `icons.ts` — `ICON_NAMES` matching `components/IconSprite.svelte`.
- `api/`, `components/`, `assets/` — see their SPEC.md files.

## Inputs / Outputs
Consumes `api/endpoints/*`; feeds the route components via stores.

## Conventions & Constraints
- Screens mutate through these modules, not by calling endpoints directly.
- Optimistic-update pattern is the norm: sync store write → background API call → revert with toast on failure.
- `icons.ts` and `IconSprite.svelte` must stay in sync (cascade).

## Open Questions
- None.
