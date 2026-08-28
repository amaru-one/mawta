## Purpose
Shared application logic: view-model types, Svelte stores, per-screen orchestration modules, and browser-capability helpers. Wire concerns live in `api/`; presentational pieces in `components/`.

## Contents
- `types.ts` — app-side (camelCase) view models: `Course`, `Student`, `Session`, `Attendance`, `Participation`, `Entry`, `CompetencyLevel`, `SiagieReport`, etc. Wire shapes live in `api/dto.ts`; mappers translate.
- `stores.ts` — writable stores: `currentCourse`, `currentSession`, `students`, `entries`, `notifications`, `teacher`, `canGoBack`, derived `unreadNotificationCount`. `canGoBack` is false until the SPA makes its first client-side navigation; `TopBar`'s `useHistory` back arrow reads it to decide between `history.back()` and its fallback href.
- `lesson.ts` — lesson-screen orchestration: loads the session roster and owns every mutation (attendance, participation, flags, mark-all-present, voice notes). Optimistic: store updates synchronously, API call in background, revert + error toast on rejection — autosave, no submit button.
- `notifications.ts` — notification feed logic backed by GET /notifications; `aiGenerated` splits alerts (accent) from reminders (neutral).
- `grades.ts` — MINEDU achievement-level vocabulary (`Tier` AD/A/B/C, labels); all grade math is server-side, the client renders codes. `Tier` doubles as the app-side type for `types.ts`'s `CompetencyLevel.level` — no separate `NivelLogro`-shaped app type.
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
- 2026-08-27: Dropped `CompetencyLevel.suggestedLevel` from `types.ts` and its mapping. Under RVM 094-2020 the nivel de logro is the teacher's judgement of evidence against the criterios; a computed level shown beside it was the framing the norm moves away from. Criterio-level data is consumed straight from `CriterionDto` — no app-side view model, matching how the grades screen already treats `StudentGradesDto`.
- 2026-08-26: Wired the niveles-de-logro/SIAGIE endpoints into the UI — `types.ts`/`mappers.ts` view models, `components/LevelPicker.svelte` + `components/CompetencyCard.svelte`, a new section in the grades screen, and a new `class/[courseId]/siagie-report` route. No new orchestration module: mutations are simple one-row-at-a-time saves, handled locally in each route like the grades screen's existing `handleScoreChange`, not the `lesson.ts`-style optimistic store pattern (that pattern earns its cost only when several interacting fields need synchronous revert, which doesn't apply here).
- 2026-08-25: Added the `canGoBack` store, set by the root layout's `afterNavigate`. Guard on `nav.type !== 'enter'`, not on `nav.from`: SvelteKit passes a non-null `from` whose `url` is null for the initial `enter` navigation, so a truthiness test on `from` is true on a cold load and would send the back arrow out of the app.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
