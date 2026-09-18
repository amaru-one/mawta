## Purpose
Notification feed screen: alerts (accented) and reminders (neutral), with mark-read actions.

## Contents
- `+page.svelte` — renders the feed from `lib/notifications.ts`; mark-read, mark-all-read.

## Inputs / Outputs
Consumes `lib/api/endpoints/notifications.ts` through `lib/notifications.ts`.

## Conventions & Constraints
- `aiGenerated` styling split is the screen's core convention, and since 2026-09-08 it is carried by **shape**: an assistant row has a **filled** accent badge, a reminder the app derived has an **outlined** one on white. Colour alone stopped being able to say it once the app's own ink became indigo (see `routes/SPEC.md`). The unread dot follows the same split: accent for the assistant's, muted for the app's.

## Open Questions
- None.
