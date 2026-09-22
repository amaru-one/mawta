## Purpose
The unguarded screen: username and password, submitted to `POST /auth/login`. Every other screen runs on the session cookie this one obtains.

## Contents
- `+page.svelte` — a full-screen form with no `TopBar`. An `h1` "Iniciar sesión" over the sub-line "Ingresa con tu usuario del colegio", two labelled fields (`Usuario` and `Contraseña`, carrying `autocomplete="username"` and `"current-password"`, disabled while submitting), a `role="alert"` line for the error, and one submit button (`.btn-block.btn-primary`) reading `Ingresar`, or `Ingresando…` while in flight. `canSubmit` requires a non-blank username, a non-empty password and no request in flight.

## Inputs / Outputs
No params and no query. Calls `login(username, password)` from `lib/api/endpoints/auth.ts` on submit. On success it derives the teacher's initials from the first two words of `display_name` and writes `teacher`, `usesInternalGrading` and `session` in `lib/stores.ts`, then `goto('/', { replaceState: true })`. On failure it renders one inline Spanish sentence and stays on the screen.

## Conventions & Constraints
- The root layout skips its `GET /me` probe on this route and sets `session` to `anonymous` instead, so this screen is where the three stores are populated on a successful login.
- Error copy is a fixed map from `ApiError.code`: `invalid_credentials` → "Usuario o contraseña incorrectos."; `account_locked` → "Demasiados intentos. Espera unos minutos e inténtalo de nuevo."; `role_not_enabled` → "El acceso para tu rol aún no está disponible."; `no_membership` → "Tu cuenta no está activa en ningún colegio."; `not_a_teacher_profile` → "Tu cuenta no tiene un perfil docente en este colegio."; anything else, including a network failure or a 5xx, falls back to "No pudimos iniciar sesión. Revisa tu conexión." A wrong username and a wrong password both come back as `invalid_credentials`.
- `client.ts` excludes `/auth/` paths from its unauthorized handler, so a 401 here reaches this component's `catch` and renders as the message above.
- The screen has no `TopBar`, no back navigation and no secondary action.
- It uses the existing `app.css` tokens and the shared `.btn-block`, `.screen-title` and `.screen-sub` classes.

## Open Questions
- None.
