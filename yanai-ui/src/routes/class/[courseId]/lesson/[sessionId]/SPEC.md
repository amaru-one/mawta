## Purpose
The lesson (attendance) screen — the app's core loop: roster with attendance and press-and-hold voice notes per student.

## Contents
- `+page.svelte` — binds to `lib/lesson.ts` (loadSession + mutations) and the roster stores; renders the section-average card (`LevelBadge`) and one `RosterRow` per student (`AttendanceControl`/`MicButton`/`VoiceNotePlayer`); search and mark-all-present.

## Inputs / Outputs
Route params `courseId`, `sessionId`; all mutations go through `lib/lesson.ts` (optimistic autosave, revert on API error).

## Conventions & Constraints
- No submit button by design — every interaction saves immediately.
- **The row shows nothing about achievement.** The section-average badge at the top is the one level on this screen, and it is about the class, not about the student being marked. See `lib/components/SPEC.md` for why a per-row level and trend were removed.
- Nothing here is risk-driven — marking absent enqueues nothing. The predictive subsystem (`risk.detect` and everything behind it) was removed whole in `migrations/00003`.

## Change Log
- 2026-08-29: The row lost its flag button along with the whole per-session observation subsystem it wrote to (`lib/components/FlagButton.svelte`, `session_observations`, `behavior_flag_types` — see `lib/components/SPEC.md` and `yanai-server/migrations/SPEC.md`); `RosterRow` now renders only `AttendanceControl` and `MicButton`. Also corrected a stale claim that marking absent still triggered `risk.detect` — that stopped in 2026-08-25, and the tables it read were dropped in `migrations/00003`.
- 2026-08-29: The roster row lost its participation control, its nivel de logro badge and its "A →" previous-tier arrow; the comment beside `sectionAverage` no longer claims the row shares its scale. The section-average card stays. Cascade from `lib/components/RosterRow.svelte`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
