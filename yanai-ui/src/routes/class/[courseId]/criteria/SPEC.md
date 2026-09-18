## Purpose
Where a teacher writes the **criterios de evaluación** for each competencia of the class's área. Under RVM 094-2020 (mod. 048-2024) these are the reference the teacher judges evidence against; without them a nivel de logro has nothing to rest on.

## Contents
- `+page.svelte` — one card per competencia, each listing its criterios with a delete action and an inline "+ Agregar criterio" composer (textarea + Cancelar/Guardar). A banner counts the competencias that still have none.

## Inputs / Outputs
Route params: `courseId` (the class id). Query: `?course=` carries the class name for the header, the same convention the grades screen uses. Calls `getClassCriteria`, `createCriterion`, `deleteCriterion` from `$lib/api/endpoints/criteria`. Linked from the class dashboard; the back arrow is `useHistory`, which handled two entry points while the end-of-period report existed and handles one now.

## Conventions & Constraints
- A competencia with **no criterios is shown, not hidden**, and counted in the banner. "This competencia has nothing to judge against" is the single most useful thing this screen can say.
- The criterio text is the teacher's own. The server rejects a blank description and a competencia outside the class's área; both surface through `showToast` rather than being pre-empted client-side, except the empty-text case, which just disables Guardar.
- Deleting is soft and the confirm dialog says so: evidence already tagged with a criterio keeps the tag, because it is part of a student's history even once the teacher stops using it.
- **A criterio is never graded — not here and nowhere else.** What a criterio does is say what to look at in a piece of work; it is the ruler, not the thing marked (RVM 094-2020, 5.1.1.3 p.3). The only judgement the app records is the **nivel de logro of the competencia**, asserted on `class/[courseId]/students/[studentId]` after reading the period's evidence. Criterios are written here and then attached to a piece of evidencia when it is filed in `class/[courseId]/evidence/new`.

## Open Questions
- Criterios cannot be edited, only added and deleted. Editing would need a supersede-style API decision (the levels recorded against a criterio reference it), so it was left out rather than half-done.
