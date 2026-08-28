## Purpose
Where a teacher writes the **criterios de evaluación** for each competencia of the class's área. Under RVM 094-2020 (mod. 048-2024) these are the reference the teacher judges evidence against; without them a nivel de logro has nothing to rest on.

## Contents
- `+page.svelte` — one card per competencia, each listing its criterios with a delete action and an inline "+ Agregar criterio" composer (textarea + Cancelar/Guardar). A banner counts the competencias that still have none.

## Inputs / Outputs
Route params: `courseId` (the class id). Query: `?course=` carries the class name for the header, the same convention the grades screen uses. Calls `getClassCriteria`, `createCriterion`, `deleteCriterion` from `$lib/api/endpoints/criteria`. Linked from the class dashboard.

## Conventions & Constraints
- A competencia with **no criterios is shown, not hidden**, and counted in the banner. "This competencia has nothing to judge against" is the single most useful thing this screen can say.
- The criterio text is the teacher's own. The server rejects a blank description and a competencia outside the class's área; both surface through `showToast` rather than being pre-empted client-side, except the empty-text case, which just disables Guardar.
- Deleting is soft and the confirm dialog says so: levels already recorded against a criterio stay, because they are part of a student's history even once the teacher stops using it.
- No levels are recorded here — this screen is authoring only. A student's level per criterio is set on the grades screen, inside the competencia card.

## Change Log
- 2026-08-27: Created, alongside the criterios API. Nothing had ever surfaced `evaluation_criteria`, so the criterios teachers are meant to supply had nowhere to be entered.

## Open Questions
- Criterios cannot be edited, only added and deleted. Editing would need a supersede-style API decision (the levels recorded against a criterio reference it), so it was left out rather than half-done.
