## Purpose
The lesson screen, the app's core loop: find one student by name, hold the bubble, leave a voice note. Every session on Home and on the área opens this screen. It renders no roster list and no attendance.

## Contents
- `+page.svelte` — a fixed one-viewport stage under `TopBar back="/class/{courseId}" useHistory recording={phase === 'recording'}`:
  - a header built from the `.metacard` context card (a `calendar` icon, the área name from `$currentCourse`, the date as "Viernes 4 de setiembre" over a hairline, then the lesson's topic or `Sin tema asignado`), the name line, a mono sub-line, the results panel, and the "Ir a {área}" button where it is shown;
  - one `RecordBubble`, anchored below the header;
  - a pinned hint and, while recording, a countdown;
  - the selected student's notes of the day as `VoiceNotePlayer` rows.
- The name line is the search field with the chosen name painted over it as an `aria-hidden` overlay, beside an `x` button. The sub-line reads `SIN COINCIDENCIAS` / `1 COINCIDENCIA` / `N COINCIDENCIAS` while searching, and `N NOTA(S) HOY` with an optional duration once a student is chosen. The hint reads "Suelta para guardar", "Mantén para grabar" or "Elige un nombre para grabar", under `aria-live="polite"`.

## Inputs / Outputs
Route params `courseId` and `sessionId`; `?from=area` is read as `cameFromArea`. Every call goes through `lib/lesson.ts`: `loadSession` on mount (one `getSession` read, which also fires `startSession` when the header status is `scheduled`), then `addNote` and `removeNote`, both optimistic with a revert and an error toast on rejection. The screen binds to the `students`, `entries`, `notes`, `currentSession` and `currentCourse` stores.

## Conventions & Constraints
- Every interaction saves immediately; there is no submit button.
- The body is a fixed stage: everything is absolutely positioned off the stage's edges or off `--bubble-anchor`, and the route sets its own `100dvh` flex column rather than using the global `.body` gutter. The bubble keeps its position and size across all three states, and only its colour and drift speed change.
- The stage's four variables on `.stage` vary by viewport and not by state: `--bubble-anchor` places the orb's centre, `--bubble-scale` shrinks it on a short screen, and `--hint-offset`, `--count-offset` and `--notes-offset` hang the hint, the countdown and the notes panel off that same anchor. The anchor is a fixed px distance from the top, under a header whose height is constant.
- The context card holds the session's identity — área, fecha (built from two `toLocaleDateString` calls so the separator does not depend on the ICU version) and the topic — all constant for the session, which is what keeps the header's height constant. The sub-line reserves its height with `min-height` when empty.
- The stage machine is `stage = phase === 'recording' ? 'recording' : (selected && !searching ? 'armed' : 'searching')`, with `panelOpen` and `showNotes` derived from it.
- "Ir a {área}" is a full-width gradient link to `/class/{courseId}`, rendered as the header's last element and gated on three conditions: the stage is not `recording`, the picker is not open, and `cameFromArea` is false. The área marks its own links `?from=area`, so a session opened from there already has the área one entry back and the back arrow reaches it; a session opened from Home carries no param and keeps the button. `cameFromArea` is read once from `page.url`, which does not change while the screen is open, since selecting a student is local state.
- The header sits at `z-index: 4` against the hint's `3`, because the results panel is part of the header.
- The notes panel is pinned from `top: calc(var(--bubble-anchor) + var(--notes-offset))` to `bottom: 0` and scrolls inside itself. Below `max-height: 800px`, and only while `showNotes` is true, `.screen.withnotes` turns `.stage` into an `overflow-y: auto` scrollbox and `.notes` drops its bottom pin for `position: static` with a matching `margin-top`, so the list flows below the fixed composition and `.notelist` stops scrolling internally. `.stage` is `flex: 1` in the `100dvh` column, so its scrollbox is one viewport tall and `TopBar` stays put while the composition scrolls away. There is no auto-scroll.
- The back arrow uses `useHistory`, independently of `cameFromArea`; the `back` href is the cold-load fallback.
- The bubble stage is one 360×360 viewBox (`cx=cy=180`, orb `r=116`, gauge ring `r=132`) in all three states.
- The roster is loaded but not listed: `addNote` returns early unless `entries` holds `entryKey(sessionId, studentId)`, so `loadSession` populates the stores anyway. Search filters `$students` client-side and wraps the matched substring in `<mark>`; `getSession`'s `q` parameter stays unused. The picker lists the whole roster when the query is empty, and each row shows initials, the name, and the student's note count for this session.
- A results row commits on release: the student is captured at `pointerdown` with the pointer captured and a `TAP_SLOP` of 10px recorded, `pointermove` past the slop cancels the pending pick, `pointercancel` aborts, and `pointerup` inside the slop calls `preventDefault()` — suppressing the compatibility click that would land on whatever the closing panel uncovers — and then `pick()`, which closes the panel and blurs the field. The row's `onclick` commits only when `event.detail === 0`, which is the keyboard and assistive-technology path.
- `.rrow` carries `touch-action: pan-y` so the browser can start scrolling the panel on the first move, plus `user-select: none` and `-webkit-touch-callout: none`; `.results` carries `overscroll-behavior: contain`. The only `preventDefault()` in the gesture is on the confirmed-tap branch of `pointerup`.
- The `x` button means two things, chosen by whether a student is picked: with a selection it clears it, re-opens the picker and focuses the field; without one it closes the panel and blurs, since the field's `onfocus` re-opens it on the next tap. Its `aria-label` follows the same split — "Borrar y elegir otro alumno" or "Cerrar lista de alumnos".
- Recording is gated on a student being chosen. While it runs, the search input is disabled, the clear button and the área link are hidden, the header drops to `opacity: .45` while staying tappable, the countdown reads `quedan {N} s` against `MAX_RECORD_SEC`, and `TopBar` swaps its bell and home shortcut for the blinking `REC` marker.
- A voice note saves in full automatically: `addNote` creates it as `draft` and chains the call that marks it `saved`, with one silent retry. `VoiceNotePlayer`'s only controls are playback and delete, the latter through a `ConfirmDialog` that ports to `document.body`. The screen toasts `Nota guardada` and `Nota eliminada`.
- Nothing on the screen carries achievement data; levels are read and written on the student's screens.
- The error state is "No se pudo cargar la sesión." over a `Reintentar` button, rendered inside the stage.

## Open Questions
- None.
