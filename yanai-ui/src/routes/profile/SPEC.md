## Purpose
The teacher's profile: identity, teaching load, term activity, and the class list.

## Contents
- `+page.svelte` — `TopBar back="/" title="Mi perfil" showBell={false}`, then an identity block (76px avatar of initials, `display_name`, the optional `title`, the school as `tenant_name · tenant_city`, and a `Desde {mes año} · N año(s)` line derived from `hired_on` through `parseDateOnly`), a three-up stats grid (`Clases`, `Alumnos`, `Semanales` as rounded `weekly_hours` plus `h`), an `ACTIVIDAD` card of four rows (Clases dictadas, `asistencias_registradas / asistencias_esperadas`, Notas de voz, Evaluaciones registradas, with the icons `presentation`, `clipboard-check`, `mic`, `checklist`), a `MIS CLASES · {totalClasses}` section grouped by grade with one row per class showing `roster_count · slots_per_week/sem`, a `Cerrar sesión` button, and a version line from the `APP_VERSION` constant.

## Inputs / Outputs
No params and no query. Calls `getProfile()` on mount and `logout()` on a confirmed sign-out. Teacher identity also comes from the `teacher` store. Each class row links to `/class/{class_id}`.

## Conventions & Constraints
- The screen is read-only apart from sign-out: the button opens a `ConfirmDialog` ("¿Cerrar sesión?" / "Tendrás que iniciar sesión de nuevo para acceder a tus clases." / "Cerrar sesión"), and confirming awaits `logout()` with errors swallowed, clears `session` and `teacher`, toasts "Sesión cerrada" and navigates to `/login` with `replaceState: true`. The server clears the cookie either way, so a failed call still proceeds.
- The class list is the app's date-independent way into an área. Home covers only the current ISO week, so a class whose sessions fall outside it is reached from here.
- A row links to the área rather than to a session, and follows the app's navigable-row idiom: `<a class="row class-row pressable">` with `hapticTap` and a trailing `chevron-right`.
- The error state is "No se pudo cargar el perfil." over a `Reintentar` button. Nothing renders while the load is in flight.

## Open Questions
- `APP_VERSION` is a hardcoded string in the component (`'Yanai v1.0.4'`), not read from `package.json` or from the build.
