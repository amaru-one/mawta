## Purpose
The notification feed: assistant alerts and app-derived reminders, with mark-read actions.

## Contents
- `+page.svelte` — `TopBar back="/" showBell={false}`, a filter pill row (`Todas`, `Alertas`, `Recordatorios`, the active one `pill-dark` and the rest `pill-light`, each carrying `aria-pressed`), then two sections — `ALERTAS · TENDENCIAS DETECTADAS` over the items where `aiGenerated` is true and `RECORDATORIOS · PENDIENTES` over the rest — and a `Marcar todas leídas` button shown while `$unreadNotificationCount > 0`.

## Inputs / Outputs
No params and no query. Reads the `notifications` and `unreadNotificationCount` stores, which the root layout fills on login and refreshes on a 60s poll. Calls `markNotificationRead(id)` and `markAllNotificationsRead()` from `lib/notifications.ts`, both of which flip the store first and fire their request with errors swallowed.

## Conventions & Constraints
- The `aiGenerated` split is carried by shape: an assistant row takes a filled accent badge and an accent unread dot, a reminder takes an outlined badge on white and a muted dot.
- The badge glyph comes from the item's own `icon` when set, otherwise from a per-type map: `risk` → `trending-down`, `tip` → `sparkles`, `reminder` → `clipboard-check`.
- An alert prefixes its message with the student's name in bold; a reminder appends `— {courseName}` the same way. The meta line joins the detail or course name, a `Leído` marker, and a relative timestamp (`Ahora`, `Hace N min`, `Hace N hora(s)`, `Hace N día(s)`).
- Tapping a row taps haptically and marks it read; it does not navigate.
- The empty state is "No hay notificaciones." The screen is store-driven, so it renders no loading or error state of its own.

## Open Questions
- None.
