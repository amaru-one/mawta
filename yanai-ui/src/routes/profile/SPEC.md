## Purpose
Teacher profile screen: identity, teaching load, and term summary stats.

## Contents
- `+page.svelte` — loads `getProfile`, renders the teacher's classes and aggregates for the current term.

## Inputs / Outputs
Consumes `lib/api/endpoints/profile.ts`; teacher identity from the `teacher` store.

## Conventions & Constraints
- Read-only screen; no mutations.

## Change Log
- 2026-08-29: Removed the "Alumnos en seguimiento" activity tile. It read `alumnos_en_seguimiento`, which the server computed from `risk_flags` — a table `migrations/00003` dropped along with the rest of the predictive subsystem, so `GET /profile` had been 500ing on any tenant with an active term. No replacement metric; the screen now shows five activity stats instead of six. Cascade: `yanai-server/internal/repo/profile.go`, `lib/api/dto.ts`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
