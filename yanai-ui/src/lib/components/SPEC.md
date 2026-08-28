## Purpose
Reusable presentational Svelte components shared across the app's screens. State and API calls stay in `lib/*.ts` modules or the owning route; these render props and emit events.

## Contents
- `TopBar.svelte` — screen header with back navigation. `back` is the destination href; adding `useHistory` makes the arrow return to the previous screen instead, falling back to `back` when there is no in-app history (cold load, refresh, deep link). Modified clicks are never hijacked, so the fallback stays openable in a new tab. `Toast.svelte` — global toast (with undo) bound to `lib/toast.ts`.
- `Icon.svelte` / `IconSprite.svelte` — SVG sprite + `<Icon name>` resolver; names typed by `lib/icons.ts` (keep in sync).
- `CourseCard.svelte` — home-screen class card. `ProgressRing.svelte` — circular progress indicator.
- `RosterRow.svelte` — one student row on the lesson screen. `AttendanceControl.svelte` — present/absent toggle. `ParticipationControl.svelte` — 0–3 participation levels. `FlagButton.svelte` — observation flag toggle.
- `MicButton.svelte` — press-and-hold recording button over `lib/recorder.ts`. `VoiceNotePlayer.svelte` — playback of stored voice notes via `fetchAudioBlob`.
- `LevelBadge.svelte` — MINEDU tier badge (AD/A/B/C via `lib/grades.ts`). `AiSummaryCard.svelte` — note-summary card on the grades screen.
- `LevelPicker.svelte` — four `LevelBadge`s in a row, tappable, for recording a nivel de logro; takes a `size` so it can render small for a criterio row and full-size for a competencia. It offers no suggestion and never auto-selects. `CriterionRow.svelte` — one criterio's text plus its own `LevelPicker`. `CompetencyCard.svelte` — accordion card wrapping the competencia's criterios (each a `CriterionRow`), then the competency-level `LevelPicker`, then the conclusión descriptiva form (textarea, "incluye recomendaciones" checkbox, draft/final actions); used by the grades screen's competencias section.
- `AddPracticeScoreDialog.svelte` — dialog for adding unofficial practice scores. `ConfirmDialog.svelte` — generic confirm modal.

## Inputs / Outputs
Props/events from route pages and `lib/` modules; no direct endpoint calls except audio fetch in `VoiceNotePlayer`.

## Conventions & Constraints
- Svelte 5 syntax; component-scoped styles using tokens from `src/app.css`.
- UI copy is Spanish.

## Change Log
- 2026-08-27: `LevelPicker` lost its `suggestedLevel` prop and the "Sugerido: X" caption, and gained `size`. `CompetencyCard` gained the criterios block above the level picker, with a caption stating that the level is the teacher's judgement and is not calculated from the criterios or the marks. Added `CriterionRow.svelte`. The criterios sit *above* the level deliberately: they are what the judgement is made against, so the reading order matches the reasoning order.
- 2026-08-26: Added `LevelPicker.svelte` and `CompetencyCard.svelte`. Both follow the app's established overflow idiom for long CNEB competency names next to fixed-width badges: `.grow{flex:1;min-width:0}` on the text (no ellipsis, free wrap), `flex-shrink:0` on badges/icons, `align-items:flex-start` on rows whose text can wrap to 2+ lines — same pattern already used by `RosterRow`'s name/badge row and the grades screen's evaluation rows.
- 2026-08-25: `TopBar` gained `useHistory`, for screens reachable from more than one place where any fixed back destination is wrong for every caller but one.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
