## Purpose
The lesson (attendance) screen — the app's core loop: roster with attendance, participation, flags, and press-and-hold voice notes per student.

## Contents
- `+page.svelte` — binds to `lib/lesson.ts` (loadSession + mutations) and the roster stores; renders `RosterRow`/`AttendanceControl`/`ParticipationControl`/`FlagButton`/`MicButton`; mark-all-present and session complete actions.

## Inputs / Outputs
Route params `courseId`, `sessionId`; all mutations go through `lib/lesson.ts` (optimistic autosave, revert on API error).

## Conventions & Constraints
- No submit button by design — every interaction saves immediately.
- Marking absent triggers server-side `risk.detect`; nothing extra to do client-side.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
