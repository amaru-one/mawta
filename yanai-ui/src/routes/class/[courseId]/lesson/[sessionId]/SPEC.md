## Purpose
The lesson screen — the app's core loop, and now a **recording screen**: find one student by name, hold the bubble, leave a voice note. There is no roster list and no attendance.

## Contents
- `+page.svelte` — binds to `lib/lesson.ts` (`loadSession` plus the three note mutations) and to the `students`/`entries`/`notes` stores. Renders a fixed stage: a header (mono meta line / the search-and-name line / a mono sub-line / the results panel), one absolutely-centred `RecordBubble`, a pinned hint and countdown, and the selected student's notes of the day as `VoiceNotePlayer` rows.

## Inputs / Outputs
Route params `courseId`, `sessionId`; every mutation goes through `lib/lesson.ts` (optimistic autosave, revert on API error). One read: `getSession` via `loadSession`.

## Conventions & Constraints
- No submit button by design — every interaction saves immediately.
- **The body is a fixed stage.** Everything is absolutely positioned off the stage's edges or its centre, and the route sets its own `100dvh` flex column instead of using the global `.body` gutter. Nothing reflows between the three states: the bubble never moves and never changes size — only its gradient and its animation speed change. The hint sits at `translateY(122px)` and the countdown at `152px` in **every** state; the approved artboard drew the hint at 126 while recording and that 4px is exactly the reflow this design forbids. The sub-line reserves its height (`min-height`) even when empty so the results panel below never jumps.
- **One 360×360 bubble stage** (`viewBox 0 0 360 360`, `cx=cy=180`, `r=88`) in all three states, so "never changes size" is structural rather than coincidental.
- **The roster is loaded but never listed.** `lesson.ts`'s `addNote` early-returns unless `entries` already holds `entryKey(sessionId, studentId)`, so `loadSession` must keep populating `students`/`entries`/`notes` even though nothing renders a list. Search filters `$students` client-side; `getSession`'s `q` parameter exists server-side and stays unused, because a roster already in the store answers between keystrokes and a round-trip would not.
- **The picker lists the whole roster when the query is empty.** With no roster anywhere else, this panel is the only route to a student, and requiring a teacher to type before any name appears would make a 30-student class unbrowsable.
- **Results rows commit on `pointerdown` with `preventDefault()`**, not on click. That suppresses the focus change so the search input never blurs out from under the tap and closes the panel before the selection resolves — the `onclick`-plus-blur-timeout version of this is flaky on iOS Safari.
- **The name line is the search field.** The chosen name is painted over an empty input as an `aria-hidden` overlay rather than set as its value, which keeps "typing replaces the name" true without a did-they-edit-it state machine.
- **Recording is gated on a student being chosen and on nothing else.** It is never gated on attendance — there is no attendance here or anywhere else in the app (see the Change Log).
- Nothing about achievement is shown. There is no `PROMEDIO DE SECCIÓN` card and no per-student level: a nivel de logro is a judgement over a period's evidence (RVM 094-2020, 5.1.1.3 p.2-3) and does not belong beside a name being recorded against. It is read and written on the student's grades screen, where the evidence is.
- No scroll position is persisted, because there is no scroll.
- Nothing here is risk-driven. The predictive subsystem (`risk.detect` and everything behind it) was removed whole in `migrations/00003`.

## Change Log
- 2026-09-02: Rebuilt as a recording-first stage from the approved design canvas (artboards `AIdle` / `Main` / `ARecording` were the measurement source of record). The roster list, the attendance controls, the `PROMEDIO DE SECCIÓN` card, the `N/M asistencia registrada` counter, the `Todos presentes` button and the `lesson-scroll:<id>` persistence are all gone. `RosterRow.svelte`, `AttendanceControl.svelte` and `MicButton.svelte` were deleted; `MicButton`'s press-and-hold machine lives on in the new `RecordBubble.svelte`, and `VoiceNotePlayer` is reused unchanged. **Attendance was dropped from this flow with no replacement screen, which removes the app's only asistencia capture** — see the repo root SPEC for the full consequence. Cascade: `lib/lesson.ts`, `lib/types.ts`, `lib/grades.ts`, `lib/recorder.ts`, `lib/components/`, `lib/api/`, `src/app.css`.
- 2026-08-29: The row lost its flag button along with the whole per-session observation subsystem it wrote to (`lib/components/FlagButton.svelte`, `session_observations`, `behavior_flag_types` — see `lib/components/SPEC.md` and `yanai-server/migrations/SPEC.md`); `RosterRow` then rendered only `AttendanceControl` and `MicButton`. Also corrected a stale claim that marking absent still triggered `risk.detect` — that stopped in 2026-08-25, and the tables it read were dropped in `migrations/00003`.
- 2026-08-29: The roster row lost its participation control, its nivel de logro badge and its "A →" previous-tier arrow; the comment beside `sectionAverage` no longer claims the row shares its scale. The section-average card stays. Cascade from `lib/components/RosterRow.svelte`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
