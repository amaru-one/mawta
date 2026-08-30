## Purpose
SvelteKit routes — the app's screens. All pages are client-rendered (static SPA).

## Contents
- `+layout.ts` — disables SSR/prerender as needed for SPA mode; `+layout.svelte` — global shell (loads `app.css`, icon sprite, toast), loads the teacher identity and the school's `usesInternalGrading` switch from `GET /me`, polls notifications, and tracks `canGoBack` via `afterNavigate` for `TopBar`'s `useHistory` arrow.
- `+page.svelte` — Home: today's classes, search, unread badge.
- `class/[courseId]/` — class dashboard (see its SPEC.md).
- `class/[courseId]/lesson/[sessionId]/` — lesson/attendance screen (see its SPEC.md).
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
- 2026-08-29: Deleted `class/[courseId]/siagie-report/`. It was read-only over data the student's grades screen already owns, and the one thing it did that nothing else could — filing evidencia for the whole class — moved to the class dashboard, which is the other screen that speaks for a class rather than for a student. `class/[courseId]/criteria/` is back to a single entry point (the dashboard); its `useHistory` arrow still handles that correctly.
- 2026-08-28: Added `class/[courseId]/evidence/[assessmentId]/`, the class-wide evidencia × criterio grid. `+layout.svelte` now also stores `tenant.uses_internal_grading` from `GET /me`, which gates every mark input in the app.
- 2026-08-27: Added `class/[courseId]/criteria/`, the screen where criterios de evaluación are authored — the layer RVM 094-2020 makes evaluation rest on and which had no UI at all. Reachable from the class dashboard, above the SIAGIE report.
- 2026-08-26: Added `class/[courseId]/siagie-report/` (screen 07 in `yanai-views.html`) and a "NIVELES DE LOGRO POR COMPETENCIA" section to `grades/[studentId]/` — six screens become seven.
- 2026-08-25: The layout now tracks `canGoBack`. Back arrows on screens with a single entry point stay hardcoded; `grades/[studentId]` uses `useHistory`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
