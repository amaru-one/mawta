## Purpose
Notification feed screen: alerts (accented) and reminders (neutral), with mark-read actions.

## Contents
- `+page.svelte` — renders the feed from `lib/notifications.ts`; mark-read, mark-all-read.

## Inputs / Outputs
Consumes `lib/api/endpoints/notifications.ts` through `lib/notifications.ts`.

## Conventions & Constraints
- `aiGenerated` styling split is the screen's core convention (alerts accent, reminders neutral).

## Change Log
- 2026-08-29: Corrected three stale claims: there is no dismiss action (`dismissNotification` and its route were deleted 2026-08-29 for want of a caller), no cursor pagination in use (`lib/notifications.ts`'s `loadNotifications` calls `getNotifications()` with no arguments even though the endpoint supports `before`), and alerts are not "risk-rule generated" — the risk subsystem was removed whole in `migrations/00003`.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
