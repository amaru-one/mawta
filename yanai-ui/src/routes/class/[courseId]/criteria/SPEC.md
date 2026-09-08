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

## Change Log
- 2026-09-08: Restyled onto the app-wide palette and type (see `src/SPEC.md`). No behaviour, copy or data change. «+ Agregar criterio» became a tinted pill and the composer's textarea took the app's field shape.
- 2026-09-04: No code change on this screen, but its central rule was **wrong and is corrected**: it said a student's level per criterio is recorded inside a piece of evidencia. Criterio levels no longer exist anywhere in the app — a criterio is a tag on evidence, and the only recorded judgement is the nivel de logro of the competencia. The screen's own job (authoring the criterios) is unchanged. See `routes/SPEC.md`.
- 2026-08-29: Back to a single entry point — the end-of-period report, which was the second one, was deleted. No code change on this screen. Cascade from `routes/class/[courseId]/`.
- 2026-08-28: No change to this screen; the note about where levels are recorded was corrected — they are now filed inside a piece of evidencia, not against the criterio for a periodo. Cascade from `routes/grades/[studentId]/` and `internal/repo/criteria.go`.
- 2026-08-28: Second entry point — the end-of-period report links here rather than growing its own copy of the composer. No code change on this screen; `useHistory` already handled the new caller. Cascade from `routes/class/[courseId]/siagie-report/`.
- 2026-08-27: Created, alongside the criterios API. Nothing had ever surfaced `evaluation_criteria`, so the criterios teachers are meant to supply had nowhere to be entered.

## Open Questions
- Criterios cannot be edited, only added and deleted. Editing would need a supersede-style API decision (the levels recorded against a criterio reference it), so it was left out rather than half-done.
