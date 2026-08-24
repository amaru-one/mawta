## Purpose
Shared application logic: view-model types, Svelte stores, per-screen orchestration modules, and browser-capability helpers. Wire concerns live in `api/`; presentational pieces in `components/`.

## Contents
- `types.ts` — app-side (camelCase) view models: `Course`, `Student`, `Session`, `Attendance`, `Participation`, `Entry`, etc. Wire shapes live in `api/dto.ts`; mappers translate.
- `stores.ts` — writable stores: `currentCourse`, `currentSession`, `students`, `entries`, `notifications`, `teacher`, derived `unreadNotificationCount`.
- `lesson.ts` — lesson-screen orchestration: loads the session roster and owns every mutation (attendance, participation, flags, mark-all-present, voice notes). Optimistic: store updates synchronously, API call in background, revert + error toast on rejection — autosave, no submit button.
- `notifications.ts` — notification feed logic backed by GET /notifications; `aiGenerated` splits alerts (accent) from reminders (neutral).
- `grades.ts` — MINEDU achievement-level vocabulary (`Tier` AD/A/B/C, labels); all grade math is server-side, the client renders codes.
- `recorder.ts` — press-and-hold MediaRecorder voice capture; mic stream kept warm after first grant; blob decode/duration helpers.
- `transcribe.ts` — stubbed transcription hook (future Whisper-style integration); not called anywhere yet.
- `toast.ts` — toast store with optional undo. `haptics.ts` — optional vibration feedback. `icons.ts` — `ICON_NAMES` matching `components/IconSprite.svelte`.
- `api/`, `components/`, `assets/` — see their SPEC.md files.

## Inputs / Outputs
Consumes `api/endpoints/*`; feeds the route components via stores.

## Conventions & Constraints
- Screens mutate through these modules, not by calling endpoints directly.
- Optimistic-update pattern is the norm: sync store write → background API call → revert with toast on failure.
- `icons.ts` and `IconSprite.svelte` must stay in sync (cascade).

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
