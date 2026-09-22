## Purpose
The área: one class seen whole — today's session, the way into its criterios, alumnos and class-wide evidencia, and rails of upcoming and past sessions. Every session on the screen, the hero included, links into that session's recording screen.

## Contents
- `+page.svelte` — `TopBar back="/" useHistory`, the class name as an `h1` over a `{roster_count} alumnos · {sessions_per_week} sesiones/semana` sub-line, then:
  - a `.hero` anchor for `next_session` when it is non-null, carrying a `Hoy · {phase}` label, the start time at 40px, `{topic ?? 'Sin tema asignado'} · termina {end}` and a trailing `chevron-right`;
  - a `.quiet` nav of three link rows — `Alumnos` / "Niveles de logro por competencia" → `students/`; `Criterios de evaluación` / "Lo que valoras en cada competencia" → `criteria/?course=`; `Añadir evidencia` / "Una evaluación para toda la clase" → `evidence/new/?course=`, whose trailing glyph is `plus` rather than a chevron;
  - a `Próximas clases` rail and a `Clases anteriores` rail of `.lcard`s, each a date block beside the topic with the time range, the past ones also carrying a 14px `mic`. The `Clases anteriores` eyebrow takes the hint "Toca una clase para dejarle una nota de voz."

## Inputs / Outputs
Route param `courseId`. Calls `getClassDashboard(courseId)` on mount and nothing else — the screen performs no mutations. The hero and both rails link to `lesson/{session_id}?from=area`. The term defaults to the current one server-side.

## Conventions & Constraints
- The hero carries `--gradient-action` and is the screen's one loud element; the rails stay tinted reference. There is no "Grabar nota de voz" button, since tapping a session already binds the note to it.
- Every link into a session carries `?from=area`, which marks that the área sits one entry behind that session in browser history — the lesson screen reads it to drop its own "Ir a {área}" button. A session opened from Home carries no such param.
- The área has two entry points: a session's "Ir a {área}" button, and `profile/`'s class list, which is the date-independent one. `TopBar`'s `useHistory` covers both.
- The hero is the whole `<a>`: today's session appears in neither rail, so the hero block is the only way to it. It borrows the `.quiet-row` chevron idiom, so a chevron means navigation everywhere on the screen.
- The hero's phase label is clock-derived rather than `status`-derived, computed in-template from `scheduled_start_at`/`scheduled_end_at` against a `now` refreshed every 60s: before the start reads `Sin iniciar`, inside the range `En curso`, past the end `Finalizada`. The server only ever puts a session dated today, `scheduled` or `in_progress`, and not yet ended into `next_session`; a finished one drops into `past`, and `cancelled`/`rescheduled` sessions do not reach the hero. The labels are written in sentence case because `.hero-lbl` uppercases them in CSS.
- Class-wide work starts here; anything scoped to one student starts on that student's screen. `evidence/new/` states its scope in a caption rather than offering a picker.
- A card's width follows its topic (`width: max-content` between 190px and 300px, then a two-line clamp), so the rail is ragged. The rails bleed past the body gutter (`margin: 0 -18px 30px` against `padding: 0 18px 8px`) so a card sits half-cut at the phone edge, which is why the gutter number is repeated here rather than inherited; the screen also overrides `.body` padding locally to `18px 20px 30px` and sets its own `.eyebrow` margin.
- `ClassDashboardDto` also carries `distribution`, `stats`, `grades_pending` and `attendance_unmarked`, and `SessionSummaryDto` carries `present_count`, `roster_count`, `missing_grades` and `has_comments`. The screen renders none of them.
- The hero, every quiet row and every rail card tap haptically. The error state is "No se pudo cargar el panel." over a `Reintentar` button.

## Open Questions
- None.
