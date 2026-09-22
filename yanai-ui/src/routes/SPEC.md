## Purpose
SvelteKit routes — the app's screens. All pages are client-rendered as a static SPA.

## Contents
- `+layout.ts` — `ssr = false` and `prerender = false`.
- `+layout.svelte` — the global shell and the auth gate. It loads `app.css`, mounts `IconSprite` and `Toast`, and links the favicon and the `viewport-fit=cover` meta into `<svelte:head>`. On mount it registers `setUnauthorizedHandler(goAnonymous)`, which any 401 outside `/auth/` routes through. On `/login` it sets `session` to `anonymous` and fires no probe; everywhere else it calls `getMe()` and, on success, derives the teacher's initials, populates `teacher`, `usesInternalGrading` and `session`, loads the notification feed and starts a 60s poll. A failed probe, whether a 401 or a network error, calls `goAnonymous()`, which clears `session` and `teacher`, stops the poll and navigates to `/login` with `replaceState: true`. `{@render children()}` is withheld while `session.status === 'unknown'`. An `afterNavigate` sets `canGoBack` on any navigation whose `type` is not `enter`, which is what `TopBar`'s `useHistory` arrow reads.
- `+page.svelte` — **Home**: one day on an hour grid. A fixed header carrying the date (`Jueves 3 SET`), a mono line counting the day's classes and their span, and a Monday-to-Friday strip, over a proportional time grid that is the only part that scrolls. Every session on the grid links to `/class/{courseId}/lesson/{sessionId}`, with no `?from=area`.
  - One hour is `HOUR_PX = 64`, so a 90-minute class draws twice a 45-minute one and a break is exactly the space it occupies. Gaps are neither rendered nor labelled.
  - The window runs `OPEN_H = 7` to `CLOSE_H = 17` every day, stretching only for a day with something outside it.
  - A session box is filled (`--surface-1`) and outlined (1px `--border-strong`), with a `-2px` seam between adjacent boxes. Each box states its own start and end in mono above the name, since the gutter marks only whole hours.
  - Hour lines are 1px and the now marker is a solid rule with a dot and an `HH:MM` label, drawn when the selected day is today and the clock sits inside the window.
  - The strip is the whole of the day navigation: five cells, Monday to Friday, with `aria-current="date"` on the selection, a dot under a day that has classes and a ring marking today while another day is being looked at. There are no arrows and no paging between weeks.
  - The screen loads once: `GET /home` answers with the asked-for day in `today` and the rest of its ISO week in `week`, so switching days does not refetch. `getHome`'s `date` parameter is left unused. `week` carries only days that have sessions, so the strip is built from computed dates.
  - A weekend `today` resolves to that week's Friday (Sunday steps back two days, Saturday one), since the strip has no weekend cell.
  - A day with no classes renders one line instead of the grid. The grid opens scrolled to the current hour, or to the first class on another day, inside an `$effect` keyed on the selection with its body in `untrack`, so a clock tick does not move the scroll.
  - Session state is clock-derived: `live` while the wall clock sits inside a session, `done` once it has ended, with `now` refreshed on a 60s interval. `status` is consulted only for a `cancelled` or `rescheduled` session, which renders muted, labelled `cancelada`, as a `<span>` rather than a link.
  - Nothing on the screen is a to-do; the work queue is the notifications feed behind the bell.
  - The class happening now takes the action gradient and white type, the rest of the day sits on `--aurora-tint`, and a finished class steps back to the page's white.
- `login/` — the unguarded route: username and password against `POST /auth/login` (see its SPEC.md).
- `class/[courseId]/` — the área: the class seen whole, a reference surface and a launcher (see its SPEC.md).
- `class/[courseId]/lesson/[sessionId]/` — the lesson recording screen: find a student by name, hold to leave a voice note (see its SPEC.md).
- `class/[courseId]/students/` — Alumnos: the class as a list of people, scoped to one competencia (see its SPEC.md).
- `class/[courseId]/students/[studentId]/` — the student's screen, where evaluating happens (see its SPEC.md).
- `class/[courseId]/criteria/` — where the teacher writes the criterios de evaluación (see its SPEC.md).
- `class/[courseId]/evidence/new/` — registering one evaluation for the class or for one student (see its SPEC.md).
- `grades/[studentId]/` — one student across the whole área (see its SPEC.md).
- `notifications/` — the notification feed (see its SPEC.md).
- `profile/` — the teacher profile, and the date-independent entry into an área through its "MIS CLASES" list (see its SPEC.md).

## Inputs / Outputs
Pages call `lib/` orchestration modules and `lib/api/endpoints/*`, and render `lib/components`.

## Conventions & Constraints
- Each route is documented by its own SPEC.md, which is the product spec for that screen; a new screen gets one in the same turn it is added.
- Every screen wears the same four things, all defined in `app.css`: a 34px/700 title with a 1.5px rule under it, a mono uppercase context line beneath it, mono `.eyebrow` section labels, and one primary action on the action gradient, with secondary ones on `--aurora-tint`. A screen that needs different numbers overrides them locally.
- Home links to a session and the área links to a session; `profile/` links to an área without a date. Home covers only the current ISO week, so `profile/`'s class list is what reaches a class whose sessions fall outside it.
- The assistant is marked by shape: an assistant row carries a filled badge with its glyph, and what the app derives itself carries an outlined one on white. The accent fills that badge, marks the AD tier and marks the bell's unread dot.
- Names no endpoint returns travel in the URL: `name`, `course`, `class` on the grades screen, and `student` for the evidence scope. `comp` persists the selected competencia through `replaceState` on both competencia-scoped screens.
- `?from=area` is written only by `class/[courseId]`, on the hero and both rails.
- Every data screen except `notifications/` holds a `ready` / `loadError` pair, renders nothing while loading, and offers a `pill-light` `Reintentar` that re-invokes its `load()`.

## Open Questions
- None.
