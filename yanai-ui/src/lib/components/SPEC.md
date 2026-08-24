## Purpose
Reusable presentational Svelte components shared across the six screens. State and API calls stay in `lib/*.ts` modules; these render props and emit events.

## Contents
- `TopBar.svelte` — screen header with back navigation. `Toast.svelte` — global toast (with undo) bound to `lib/toast.ts`.
- `Icon.svelte` / `IconSprite.svelte` — SVG sprite + `<Icon name>` resolver; names typed by `lib/icons.ts` (keep in sync).
- `CourseCard.svelte` — home-screen class card. `ProgressRing.svelte` — circular progress indicator.
- `RosterRow.svelte` — one student row on the lesson screen. `AttendanceControl.svelte` — present/absent toggle. `ParticipationControl.svelte` — 0–3 participation levels. `FlagButton.svelte` — observation flag toggle.
- `MicButton.svelte` — press-and-hold recording button over `lib/recorder.ts`. `VoiceNotePlayer.svelte` — playback of stored voice notes via `fetchAudioBlob`.
- `LevelBadge.svelte` — MINEDU tier badge (AD/A/B/C via `lib/grades.ts`). `AiSummaryCard.svelte` — note-summary card on the grades screen.
- `AddPracticeScoreDialog.svelte` — dialog for adding unofficial practice scores. `ConfirmDialog.svelte` — generic confirm modal.

## Inputs / Outputs
Props/events from route pages and `lib/` modules; no direct endpoint calls except audio fetch in `VoiceNotePlayer`.

## Conventions & Constraints
- Svelte 5 syntax; component-scoped styles using tokens from `src/app.css`.
- UI copy is Spanish.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
