## Purpose
SvelteKit routes — the app's screens. All pages are client-rendered (static SPA).

## Contents
- `+layout.ts` — disables SSR/prerender as needed for SPA mode; `+layout.svelte` — global shell (loads `app.css`, icon sprite, toast), loads the teacher identity and the school's `usesInternalGrading` switch from `GET /me`, polls notifications, and tracks `canGoBack` via `afterNavigate` for `TopBar`'s `useHistory` arrow.
- `+page.svelte` — **Home: the teacher's day as an agenda.** The date (`Martes 1 SET`) and a mono line counting the day and its span, then a **time rail**: an hour column on the left and each session in the hour it starts, hairline-ruled row by row. An hour with nothing in it renders as one empty slot, so a free midday reads as a gap in time rather than as two adjacent rows. A **now marker** — a dot, a rule and the wall-clock time — sits above the first session that has not ended, and drops to the foot of the rail once the day is over; it is drawn only when the payload's date really is today. Below, **La semana**: the rest of the ISO week, a day gutter (`LUN` / `31`) beside one tappable line per class, with days already past attenuated. Every row opens that session's lesson screen. Search is folded behind an icon and filters both sections by class name.
  - Row state is **clock-derived**, as on the class dashboard: `en curso` while the wall clock sits inside a session, muted once it has ended. `status` is consulted only to mark a `cancelled`/`rescheduled` session, which renders muted, labelled `cancelada`, and is not a link. `now` refreshes on a 60s interval so the screen keeps up with the day.
  - **Nothing on this screen is a to-do.** No pending-grade counts, no missing-attendance badges, no unwritten-comment prompts — the agenda states facts about time. The teacher's work queue is the notifications feed, reached from the bell.
  - The now marker is **black** (`--fill-primary`), not the accent: `app.css` reserves `#5b5fc7` for assistant-generated signals, and this screen follows the dashboard's rule that emphasis comes from one dark element.
  - Like the class dashboard, it overrides the global `.body` gutter (`22px 18px 30px`) and `.eyebrow`; the rail's 50px hour column is measured against that gutter.
- `class/[courseId]/` — class dashboard (see its SPEC.md).
- `class/[courseId]/lesson/[sessionId]/` — the lesson recording screen: find a student by name, hold to leave a voice note (see its SPEC.md).
- `class/[courseId]/criteria/` — where the teacher writes the criterios de evaluación for each competencia (see its SPEC.md).
- `class/[courseId]/evidence/[assessmentId]/` — the evidencia × criterio grid for one piece of evidence across the whole class, the marking view (see its SPEC.md).
- `grades/[studentId]/` — student grades (see its SPEC.md).
- `notifications/` — notification feed (see its SPEC.md).
- `profile/` — teacher profile (see its SPEC.md).

## Inputs / Outputs
Pages call `lib/` orchestration modules and endpoints, render `lib/components`.

## Conventions & Constraints
- Each route is documented by its own SPEC.md, which is the product spec for that screen — there is no separate mock or gallery to keep in step with. A new screen gets a SPEC.md in the same turn it's added.

## Change Log
- 2026-09-02: `class/[courseId]/lesson/[sessionId]/` was rebuilt from a roster with attendance into a recording screen: the name line is the search field, the results panel hangs off it and floats over a bubble that is absolutely centred and never moves, and holding that bubble records a voice note for the one selected student. The roster list, the attendance controls, the section-average card and the mark-all-present action are gone. **Attendance now has no home anywhere in the app** — this is a product decision, recorded in full in the repo root SPEC. Cascade: `lib/`, `lib/api/`, `lib/components/`, `src/app.css`.
- 2026-09-01: Home was rebuilt from a searchable list of class cards into a day agenda (see its Contents entry). It renders `HomeDto` directly with local formatters, as the class dashboard does, so `toHomeCourses`, the `HomeCourse`/`CourseStatus` view models and `components/CourseCard.svelte` are all deleted — Home was their only consumer. Two things the old screen had and the new one drops: the subject icon tile (the agenda is typographic, so `icon_key` is no longer read at all) and the always-visible search field, now folded behind an icon. Two it gains: `room` and `topic` from the widened `GET /home`, and a link straight to `/class/{id}/lesson/{sessionId}` — Home knew today's `session_id` all along and still sent the teacher to the class dashboard to find it. The week section is now dated days rather than a recurring weekly pattern, which also fixes a real omission: a class that met today used to vanish from the rest of the week entirely. Cascade: `lib/`, `lib/api/`, `lib/components/`, `yanai-server/internal/repo`, `yanai-server/internal/httpapi`.
- 2026-08-29: Deleted `class/[courseId]/siagie-report/`. It was read-only over data the student's grades screen already owns, and the one thing it did that nothing else could — filing evidencia for the whole class — moved to the class dashboard, which is the other screen that speaks for a class rather than for a student. `class/[courseId]/criteria/` is back to a single entry point (the dashboard); its `useHistory` arrow still handles that correctly.
- 2026-08-28: Added `class/[courseId]/evidence/[assessmentId]/`, the class-wide evidencia × criterio grid. `+layout.svelte` now also stores `tenant.uses_internal_grading` from `GET /me`, which gates every mark input in the app.
- 2026-08-27: Added `class/[courseId]/criteria/`, the screen where criterios de evaluación are authored — the layer RVM 094-2020 makes evaluation rest on and which had no UI at all. Reachable from the class dashboard, above the SIAGIE report.
- 2026-08-26: Added `class/[courseId]/siagie-report/` (screen 07 in `yanai-views.html`) and a "NIVELES DE LOGRO POR COMPETENCIA" section to `grades/[studentId]/` — six screens become seven.
- 2026-08-25: The layout now tracks `canGoBack`. Back arrows on screens with a single entry point stay hardcoded; `grades/[studentId]` uses `useHistory`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
