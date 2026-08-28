## Purpose
Read-only end-of-period report for one class: the niveles de logro (AD/A/B/C) every student has per competencia, and which mandatory conclusiones descriptivas are still missing before the period can be considered ready to send. Mirrors what SIAGIE expects to receive (RVM 094-2020, modificada por RVM 048-2024).

## Contents
- `+page.svelte` — loads `getSiagieReport(courseId)` → `toSiagieReport`; renders the server's `notice` text, a blocking banner when `!ready`, and one accordion card per student (name + "N/M completas" + one row per competencia, level badge or dash when `level === null`).

## Inputs / Outputs
Route param `courseId`; reads via `lib/api/endpoints/competencies.ts`'s `getSiagieReport`. No mutations — this screen is read-only by design; gaps are fixed from the student's grades screen (`/grades/[studentId]`), not here.

## Conventions & Constraints
- Single entry point (the class dashboard's "Reporte de fin de periodo" row) — the back arrow is a hardcoded `back` href, not `useHistory` (per `routes/SPEC.md`'s stated convention for single-entry screens).
- No table/grid of students × competencias — the whole app has zero responsive breakpoints beyond a 480px phone frame, so this is a pure vertical list of per-student accordions, same pattern as the grades screen's evaluation modules. Do not add a wide table here.
- `comp.level === null` renders as a dash, never as C — "not developed this period" is a valid, distinct state (5.1.2.2 p.1).
- Long competency names follow the app's overflow idiom: `.grow{flex:1;min-width:0}` on the text, no ellipsis, `flex-shrink:0` on the badge/dash, `align-items:flex-start` since names can wrap to 2+ lines.

## Change Log
- 2026-08-26: Initial version, connecting the `GET .../siagie-report` endpoint added this session.

## Open Questions
- No term selector — defaults to the server's current term (`term_id` query omitted), same as the grades and class dashboard screens. Revisit if a school needs to review a past bimestre's report after the term closed.
