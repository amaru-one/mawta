## Purpose
Shared application logic: view-model types, Svelte stores, per-screen orchestration modules, and browser-capability helpers. Wire concerns live in `api/`; presentational pieces in `components/`.

## Contents
- `types.ts` — app-side (camelCase) view models: `Course`, `Student`, `Session`, `Attendance`, `Entry`, `CompetencyLevel`, etc. Wire shapes live in `api/dto.ts`; mappers translate.
- `stores.ts` — writable stores: `currentCourse`, `currentSession`, `students`, `entries`, `notes`, `notifications`, `teacher`, `canGoBack`, `usesInternalGrading`, derived `unreadNotificationCount`; `entryKey(sessionId, studentId)` builds the natural key `entries`/`notes` are keyed by. `usesInternalGrading` mirrors `GET /me`'s `tenant.uses_internal_grading` — whether the school runs its own weighted numeric system (D.S. 009-2006-ED art. 37.4.f). It defaults to true so a screen rendered before `/me` resolves looks like the historical app, and it gates mark inputs and the internal-grade card only: niveles de logro never depend on it, since the official record never comes from a number either way. `canGoBack` is false until the SPA makes its first client-side navigation; `TopBar`'s `useHistory` back arrow reads it to decide between `history.back()` and its fallback href.
- `lesson.ts` — lesson-screen orchestration: loads the session roster and owns every mutation (attendance, mark-all-present, voice notes). Optimistic: store updates synchronously, API call in background, revert + error toast on rejection — autosave, no submit button.
- `notifications.ts` — notification feed logic backed by GET /notifications; `aiGenerated` splits alerts (accent) from reminders (neutral).
- `grades.ts` — MINEDU achievement-level vocabulary (`Tier` AD/A/B/C, labels); all grade math is server-side, the client renders codes. `Tier` doubles as the app-side type for `types.ts`'s `CompetencyLevel.level` — no separate `NivelLogro`-shaped app type.
- `recorder.ts` — press-and-hold MediaRecorder voice capture; mic stream kept warm after first grant; blob decode and duration formatting helpers.
- `toast.ts` — toast store with optional undo. `haptics.ts` — optional vibration feedback. `icons.ts` — `ICON_NAMES` matching `components/IconSprite.svelte`.
- `api/`, `components/`, `assets/` — see their SPEC.md files.

## Inputs / Outputs
Consumes `api/endpoints/*`; feeds the route components via stores.

## Conventions & Constraints
- Screens mutate through these modules, not by calling endpoints directly.
- Optimistic-update pattern is the norm: sync store write → background API call → revert with toast on failure.
- `icons.ts` and `IconSprite.svelte` must stay in sync (cascade).

## Change Log
- 2026-08-29: Second purge pass. Deleted `transcribe.ts` whole (never called, and since the same day's earlier pass there is no endpoint left to post a transcript to). `Entry` lost `flagged`/`flagTypeIds`/`observationNote`, and `lesson.ts` lost `setFlag`/`ensureFlagTypes`/`defaultFlagTypeId` and the `getFlagTypes` call in `loadSession` — the whole per-session observation subsystem they wrote to is gone server-side (`yanai-server/migrations/00007`), and the flag catalog had no seed or provisioning path in any environment, so it could never have raised a flag anyway. `TeacherIdentity` and `parseTimestamp` (in `api/mappers.ts`) are no longer exported — both are used only inside their own file. Cascade: `api/`, `components/RosterRow.svelte`, `components/FlagButton.svelte` (deleted), `yanai-server`.
- 2026-08-29: Purge pass. `Entry` lost `participation`, `levelCode`, `previousLevelCode` and `trend`, and the `Participation` type went with them — the lesson row no longer shows a participation rating, a nivel de logro badge or a trend arrow. `lesson.ts` lost `setParticipation`, stopped sending `participation_level` on the observation PUT (which is authoritative, so a stale field there would have silently rewritten the server's row), and lost `refreshSession`, which nothing called. `types.ts` also lost the SIAGIE report view models with the screen that read them, and `recorder.ts` lost `blobDuration`. Cascade: `api/`, `components/`, `routes/`, `yanai-server`.
- 2026-08-28: `stores.ts` gained `usesInternalGrading`, set once by the root layout from `GET /me`. Read by the grades screen and both `AddEvidenceDialog` callers. Cascade from `api/dto.ts` and `yanai-server/internal/repo/me.go`.
- 2026-08-27: Dropped `CompetencyLevel.suggestedLevel` from `types.ts` and its mapping. Under RVM 094-2020 the nivel de logro is the teacher's judgement of evidence against the criterios; a computed level shown beside it was the framing the norm moves away from. Criterio-level data is consumed straight from `CriterionDto` — no app-side view model, matching how the grades screen already treats `StudentGradesDto`.
- 2026-08-26: Wired the niveles-de-logro/SIAGIE endpoints into the UI — `types.ts`/`mappers.ts` view models, `components/LevelPicker.svelte` + `components/CompetencyCard.svelte`, a new section in the grades screen, and a new `class/[courseId]/siagie-report` route. No new orchestration module: mutations are simple one-row-at-a-time saves, handled locally in each route like the grades screen's existing `handleScoreChange`, not the `lesson.ts`-style optimistic store pattern (that pattern earns its cost only when several interacting fields need synchronous revert, which doesn't apply here).
- 2026-08-25: Added the `canGoBack` store, set by the root layout's `afterNavigate`. Guard on `nav.type !== 'enter'`, not on `nav.from`: SvelteKit passes a non-null `from` whose `url` is null for the initial `enter` navigation, so a truthiness test on `from` is true on a cold load and would send the back arrow out of the app.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
