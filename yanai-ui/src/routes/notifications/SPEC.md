## Purpose
Notification feed screen: alerts (accented) and reminders (neutral), with mark-read actions.

## Contents
- `+page.svelte` — renders the feed from `lib/notifications.ts`; mark-read, mark-all-read.

## Inputs / Outputs
Consumes `lib/api/endpoints/notifications.ts` through `lib/notifications.ts`.

## Conventions & Constraints
- `aiGenerated` styling split is the screen's core convention, and since 2026-09-08 it is carried by **shape**: an assistant row has a **filled** accent badge, a reminder the app derived has an **outlined** one on white. Colour alone stopped being able to say it once the app's own ink became indigo (see `routes/SPEC.md`). The unread dot follows the same split: accent for the assistant's, muted for the app's.

## Change Log
- 2026-09-08: Restyled onto the app-wide palette and type, and the alert/reminder distinction became filled-vs-outlined rather than accent-vs-neutral. Title 20 → 34px with the shared rule beside "Marcar todas leídas"; filters are now the shared pills.
- 2026-08-29: Corrected three stale claims: there is no dismiss action (`dismissNotification` and its route were deleted 2026-08-29 for want of a caller), no cursor pagination in use (`lib/notifications.ts`'s `loadNotifications` calls `getNotifications()` with no arguments even though the endpoint supports `before`), and alerts are not "risk-rule generated" — the risk subsystem was removed whole in `migrations/00003`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
