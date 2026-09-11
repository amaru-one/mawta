## Purpose
Teacher profile screen: identity, teaching load, and term summary stats.

## Contents
- `+page.svelte` — loads `getProfile`, renders the teacher's classes and aggregates for the current term.

## Inputs / Outputs
Consumes `lib/api/endpoints/profile.ts`; teacher identity from the `teacher` store.

## Conventions & Constraints
- Read-only apart from one action: "Cerrar sesión" calls `lib/api/endpoints/auth.ts`'s `logout()`, clears the `session`/`teacher` stores, and navigates to `/login` with `replaceState: true`. It proceeds to `/login` even if the `logout()` call itself fails — `handleLogout` server-side always clears the cookie regardless, so there is nothing to retry.

## Change Log
- 2026-09-11: "Cerrar sesión" is real. It was previously UI-only (a toast and a `goto('/')`, with no session to actually end); it now calls `logout()`, updates `session`/`teacher`, and lands on `/login`. Cascade: `lib/api/endpoints/auth.ts`, `lib/stores.ts`.
- 2026-09-08: Restyled onto the app-wide palette and type (see `src/SPEC.md`). No behaviour, copy or data change. The identity block is this screen's title, so it carries the same 34px and rule as every other screen's; the avatar takes the tile gradient, the stats sit on `--aurora-tint`, and each activity row gained a tinted icon tile.
- 2026-08-29: Removed the "Alumnos en seguimiento" activity tile. It read `alumnos_en_seguimiento`, which the server computed from `risk_flags` — a table `migrations/00003` dropped along with the rest of the predictive subsystem, so `GET /profile` had been 500ing on any tenant with an active term. No replacement metric; the screen now shows five activity stats instead of six. Cascade: `yanai-server/internal/repo/profile.go`, `lib/api/dto.ts`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
