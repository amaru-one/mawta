## Purpose
Where a teacher writes the criterios de evaluación for each competencia of the class's área — the reference a piece of evidencia is read against.

## Contents
- `+page.svelte` — `TopBar back="/class/{courseId}" useHistory`, the title "Criterios de evaluación" over the class name, an intro paragraph stating that criterios are not averaged and not converted into a mark, a notice row with an `alert` icon counting the competencias that still have none, then one card per competencia: its name, a "Competencia transversal" line when `kind` is `transversal`, and its criterios as rows of description beside a trash button, or "Sin criterios definidos."
  - The composer is inline and single-instance: `+ Agregar criterio` swaps itself for a three-row textarea with a worked-example placeholder, plus `Cancelar` and `Guardar`. `composingFor` holds the competencia being written into and `draft` the text.

## Inputs / Outputs
Route param `courseId`. `?course=` carries the class name for the sub-line, the same convention the grades screen uses. Calls `getClassCriteria` on mount and again after every write, `createCriterion(courseId, competencyId, { description })` and `deleteCriterion(criterionId)`. Linked from the área.

## Conventions & Constraints
- A competencia with no criterios is listed and counted in the notice rather than hidden.
- The criterio text is the teacher's own. The server rejects a blank description and a competencia outside the class's área, and both surface through `showToast`; the blank case also keeps `Guardar` disabled.
- Writes are not optimistic: a save closes the composer, clears the draft and refetches. `reload()` swallows its own errors and keeps the last good data on screen.
- Deleting is soft, and the confirm dialog says so — "Los niveles ya registrados contra él se conservan como parte del historial." Toasts are `Criterio guardado`, `Criterio eliminado`, and `No se pudo guardar` / `No se pudo eliminar` on failure, with `ApiError.message` passed through when the server sent one.
- Criterios are written here and attached to a piece of evidencia in `class/[courseId]/evidence/new`. The judgement the app records is the nivel de logro of the competencia, asserted on `class/[courseId]/students/[studentId]`.
- The error state is the line "No se pudieron cargar los criterios."

## Open Questions
- The error state is the one among the data screens with no `Reintentar` button.
- Criterios can be added and deleted but not edited. Editing would need a supersede-style API decision, since the levels recorded against a criterio reference it.
