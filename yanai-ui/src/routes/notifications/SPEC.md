## Purpose
Notification feed screen: alerts (risk-rule generated, accented) and reminders (neutral), with read/dismiss actions.

## Contents
- `+page.svelte` — renders the feed from `lib/notifications.ts`; mark-read, mark-all-read, dismiss; cursor pagination via `before`.

## Inputs / Outputs
Consumes `lib/api/endpoints/notifications.ts` through `lib/notifications.ts`.

## Conventions & Constraints
- `aiGenerated` styling split is the screen's core convention (alerts accent, reminders neutral).

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
