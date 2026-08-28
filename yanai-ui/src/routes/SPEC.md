## Purpose
SvelteKit routes — the seven screens of `yanai-views.html`. All pages are client-rendered (static SPA).

## Contents
- `+layout.ts` — disables SSR/prerender as needed for SPA mode; `+layout.svelte` — global shell (loads `app.css`, icon sprite, toast), loads the teacher identity and polls notifications, and tracks `canGoBack` via `afterNavigate` for `TopBar`'s `useHistory` arrow.
- `+page.svelte` — Home: today's classes, search, unread badge.
- `class/[courseId]/` — class dashboard (see its SPEC.md).
- `class/[courseId]/lesson/[sessionId]/` — lesson/attendance screen (see its SPEC.md).
- `class/[courseId]/criteria/` — where the teacher writes the criterios de evaluación for each competencia (see its SPEC.md).
- `class/[courseId]/siagie-report/` — end-of-period niveles-de-logro report (see its SPEC.md).
- `grades/[studentId]/` — student grades (see its SPEC.md).
- `notifications/` — notification feed (see its SPEC.md).
- `profile/` — teacher profile (see its SPEC.md).

## Inputs / Outputs
Pages call `lib/` orchestration modules and endpoints, render `lib/components`.

## Conventions & Constraints
- Screen structure mirrors `yanai-views.html`; new screens should be added there first (it is the product spec).

## Change Log
- 2026-08-27: Added `class/[courseId]/criteria/`, the screen where criterios de evaluación are authored — the layer RVM 094-2020 makes evaluation rest on and which had no UI at all. Reachable from the class dashboard, above the SIAGIE report.
- 2026-08-26: Added `class/[courseId]/siagie-report/` (screen 07 in `yanai-views.html`) and a "NIVELES DE LOGRO POR COMPETENCIA" section to `grades/[studentId]/` — six screens become seven.
- 2026-08-25: The layout now tracks `canGoBack`. Back arrows on screens with a single entry point stay hardcoded; `grades/[studentId]` uses `useHistory`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
