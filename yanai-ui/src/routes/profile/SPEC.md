## Purpose
Teacher profile screen: identity, teaching load, and term summary stats.

## Contents
- `+page.svelte` — loads `getProfile`, renders the teacher's classes and aggregates for the current term.

## Inputs / Outputs
Consumes `lib/api/endpoints/profile.ts`; teacher identity from the `teacher` store.

## Conventions & Constraints
- Read-only screen; no mutations.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
