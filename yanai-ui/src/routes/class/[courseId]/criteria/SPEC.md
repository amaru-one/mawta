## Purpose
Where a teacher writes the **criterios de evaluación** for each competencia of the class's área. Under RVM 094-2020 (mod. 048-2024) these are the reference the teacher judges evidence against; without them a nivel de logro has nothing to rest on.

## Contents
- `+page.svelte` — one card per competencia, each listing its criterios with a delete action and an inline "+ Agregar criterio" composer (textarea + Cancelar/Guardar). A banner counts the competencias that still have none.

## Inputs / Outputs
Route params: `courseId` (the class id). Query: `?course=` carries the class name for the header, the same convention the grades screen uses. Calls `getClassCriteria`, `createCriterion`, `deleteCriterion` from `$lib/api/endpoints/criteria`. Linked from the class dashboard; the back arrow is `useHistory`, which handled two entry points while the end-of-period report existed and handles one now.

## Conventions & Constraints
- A competencia with **no criterios is shown, not hidden**, and counted in the banner. "This competencia has nothing to judge against" is the single most useful thing this screen can say.
- The criterio text is the teacher's own. The server rejects a blank description and a competencia outside the class's área; both surface through `showToast` rather than being pre-empted client-side, except the empty-text case, which just disables Guardar.
- Deleting is soft and the confirm dialog says so: levels already recorded against a criterio stay, because they are part of a student's history even once the teacher stops using it.
- No levels are recorded here — this screen is authoring only. A student's level per criterio is set inside a piece of evidencia: on the grades screen's evidence rows, or on `class/[courseId]/evidence/[assessmentId]` for the whole class at once. Never against the criterio on its own — the criterio is the ruler, not the thing marked (RVM 094-2020, 5.1.1.3 p.3).

## Change Log
- 2026-08-29: Back to a single entry point — the end-of-period report, which was the second one, was deleted. No code change on this screen. Cascade from `routes/class/[courseId]/`.
- 2026-08-28: No change to this screen; the note about where levels are recorded was corrected — they are now filed inside a piece of evidencia, not against the criterio for a periodo. Cascade from `routes/grades/[studentId]/` and `internal/repo/criteria.go`.
- 2026-08-28: Second entry point — the end-of-period report links here rather than growing its own copy of the composer. No code change on this screen; `useHistory` already handled the new caller. Cascade from `routes/class/[courseId]/siagie-report/`.
- 2026-08-27: Created, alongside the criterios API. Nothing had ever surfaced `evaluation_criteria`, so the criterios teachers are meant to supply had nowhere to be entered.

## Open Questions
- Criterios cannot be edited, only added and deleted. Editing would need a supersede-style API decision (the levels recorded against a criterio reference it), so it was left out rather than half-done.
