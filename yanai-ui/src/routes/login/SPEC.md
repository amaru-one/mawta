## Purpose
The only unguarded screen: username + password, submitted to `POST /auth/login`. Everything else in the app requires the session cookie this screen obtains.

## Contents
- `+page.svelte` — a full-screen form, no `TopBar` (there is nowhere to go back to). Two fields (`Usuario`, `Contraseña`) with `autocomplete="username"`/`"current-password"` so password managers work, one primary submit (`.btn-block.btn-primary`, the same class the rest of the app uses for its one primary action per screen). On success it populates `teacher`/`usesInternalGrading`/`session` itself — the same three the root layout's `GET /me` probe sets — and navigates to `/` with `replaceState: true` so the back button doesn't return to the login form. On failure it shows one inline Spanish sentence and stays put; it never navigates away from itself.

## Inputs / Outputs
Calls `lib/api/endpoints/auth.ts`'s `login`. Writes `lib/stores.ts`'s `session` and `teacher` directly (not via the layout) since the layout's own probe is deliberately skipped on this route — see below.

## Conventions & Constraints
- **The root layout does not probe `GET /me` on this route.** Every other screen depends on that probe to populate the shell, but firing it here would 401 on a page that must be reachable with no session at all. This screen is therefore the one place in the app that sets `session`/`teacher` itself, on a successful login, rather than letting the layout do it.
- **Error copy is a fixed map from `ApiError.code`**, mirroring `internal/httpapi/SPEC.md`'s login error codes exactly — `invalid_credentials`, `account_locked`, `role_not_enabled`, `no_membership`, `not_a_teacher_profile`, and a generic fallback for anything else (network failure, 5xx). A wrong username and a wrong password are indistinguishable on purpose (`invalid_credentials` covers both, and an inactive account too) — the UI must not add distinguishing copy the server deliberately declines to give it.
- `client.ts`'s unauthorized handler is deliberately **not** what drives this screen's errors: a 401 from `POST /auth/login` is excluded from that handler (see `lib/api/SPEC.md`) so it reaches this component's own `catch` instead of bouncing back to `/login` and losing the message.
- No `TopBar`, no back navigation, no secondary action. A teacher who can't log in has nothing else to do on this screen.
- Uses only existing `app.css` tokens and the shared `.btn-block`/`.screen-title`/`.screen-sub` classes — no new shared token or class.

## Change Log
- 2026-09-11: Created for real authentication. See `yanai-server/internal/httpapi/SPEC.md` for the login sequence and error codes this screen mirrors, `src/routes/SPEC.md` for the layout's auth gate, and `src/lib/api/SPEC.md` for the client-side session plumbing.

## Open Questions
- None.
