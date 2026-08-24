## Purpose
Class dashboard screen for one class: header stats, per-component grade-registration progress, session list, entry to lessons and student grades.

## Contents
- `+page.svelte` — loads `getClassDashboard` + `getClassSessions`, renders attendance/at-risk stats, component progress, and session navigation; can start a session.

## Inputs / Outputs
Route param `courseId` (class UUID); consumes `lib/api/endpoints/classes.ts`.

## Conventions & Constraints
- Term selection defaults to the current term server-side (`term_id` query optional).

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
