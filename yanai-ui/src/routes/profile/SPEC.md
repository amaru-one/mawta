## Purpose
Teacher profile screen: identity, teaching load, and term summary stats.

## Contents
- `+page.svelte` — loads `getProfile`, renders the teacher's classes and aggregates for the current term. The "MIS CLASES" list is navigation: each row links to that class's área (`/class/{class_id}`).

## Inputs / Outputs
Consumes `lib/api/endpoints/profile.ts`; teacher identity from the `teacher` store. `ProfileDto.classes_by_grade[].classes[].class_id` — previously read only as an `{#each}` key — is now the `href` for each class row.

## Conventions & Constraints
- Read-only apart from one action: "Cerrar sesión" calls `lib/api/endpoints/auth.ts`'s `logout()`, clears the `session`/`teacher` stores, and navigates to `/login` with `replaceState: true`. It proceeds to `/login` even if the `logout()` call itself fails — `handleLogout` server-side always clears the cookie regardless, so there is nothing to retry.
- **This screen is the app's only date-independent way into an área**, and that is load-bearing rather than incidental. Home is bounded to the current ISO week, so a class whose sessions all fall outside it (a past term, a term not yet started) is reachable from nowhere else — every other path to an área runs through a session on Home. The rows therefore follow the app's navigable-row idiom in full: `<a class="row class-row pressable">` with `hapticTap` and a trailing `chevron-right`, because "a chevron means it navigates" holds app-wide (see `routes/class/[courseId]/SPEC.md`). The class list must not go back to being an inert summary without another entry point replacing it.
- The row links to the **área**, not to a session — unlike Home, which always links to a specific session's recording screen. There is no session to prefer here: the list is date-independent, which is the whole point, so it hands off to the screen that shows the class whole and lets the teacher pick.

## Change Log
- 2026-09-13: **Each "MIS CLASES" row now links to its área** (`/class/{class_id}`), with a trailing chevron and `hapticTap`. Fixes a real dead end rather than adding a shortcut: with a dataset whose sessions are all in the past, Home renders empty (it is bounded to the current ISO week) and the área's only entry point was the "Ir a {área}" button inside a session's recording screen — itself reached from Home — so those classes were unreachable through the UI. No server, DTO or API-client change: `class_id` was already on `ProfileDto`, used only as an `{#each}` key. Cascade: `routes/class/[courseId]/SPEC.md` (its `?from=area` rule claimed the bubble was "the one path" to área — no longer true), `routes/SPEC.md`.
- 2026-09-11: "Cerrar sesión" is real. It was previously UI-only (a toast and a `goto('/')`, with no session to actually end); it now calls `logout()`, updates `session`/`teacher`, and lands on `/login`. Cascade: `lib/api/endpoints/auth.ts`, `lib/stores.ts`.
- 2026-09-08: Restyled onto the app-wide palette and type (see `src/SPEC.md`). No behaviour, copy or data change. The identity block is this screen's title, so it carries the same 34px and rule as every other screen's; the avatar takes the tile gradient, the stats sit on `--aurora-tint`, and each activity row gained a tinted icon tile.
- 2026-08-29: Removed the "Alumnos en seguimiento" activity tile. It read `alumnos_en_seguimiento`, which the server computed from `risk_flags` — a table `migrations/00003` dropped along with the rest of the predictive subsystem, so `GET /profile` had been 500ing on any tenant with an active term. No replacement metric; the screen now shows five activity stats instead of six. Cascade: `yanai-server/internal/repo/profile.go`, `lib/api/dto.ts`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
