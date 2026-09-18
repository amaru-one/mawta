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

## Open Questions
- None.
