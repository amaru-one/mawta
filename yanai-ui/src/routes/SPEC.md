## Purpose
SvelteKit routes — the six screens of `yanai-views.html`. All pages are client-rendered (static SPA).

## Contents
- `+layout.ts` — disables SSR/prerender as needed for SPA mode; `+layout.svelte` — global shell (loads `app.css`, icon sprite, toast).
- `+page.svelte` — Home: today's classes, search, unread badge.
- `class/[courseId]/` — class dashboard (see its SPEC.md).
- `class/[courseId]/lesson/[sessionId]/` — lesson/attendance screen (see its SPEC.md).
- `grades/[studentId]/` — student grades (see its SPEC.md).
- `notifications/` — notification feed (see its SPEC.md).
- `profile/` — teacher profile (see its SPEC.md).

## Inputs / Outputs
Pages call `lib/` orchestration modules and endpoints, render `lib/components`.

## Conventions & Constraints
- Screen structure mirrors `yanai-views.html`; new screens should be added there first (it is the product spec).

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
