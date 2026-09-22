## Purpose
One student across the whole área, organised by grading component: the inventory of everything filed for them. It opens with the official record (the nivel de logro per competencia), then the evidencia with its values, then the school's optional internal weighted grade, collapsed.

Its sibling is `class/[courseId]/students/[studentId]`, which takes one competencia at a time and puts that competencia's evidence directly above the decision.

## Contents
- `+page.svelte` — `TopBar` with `useHistory` and a `/class/{classId}` fallback, the student's name as the title over the course name, then four sections in order: `NIVELES DE LOGRO POR COMPETENCIA` (one `CompetencyCard` per competencia, each carrying that competencia's criterios), `EVIDENCIA` (accordions grouped by grading component, plus the "Añadir evidencia" link), the collapsed `Sistema interno de la IE` card, and `NOTAS PERSONALES` with "Añadir nota personal".

## Inputs / Outputs
Route param `studentId`. `?class=`, `?name=` and `?course=` carry the class id, the student name and the class name, since no endpoint returns them and there is no other student lookup. Reads `getStudentGrades`, `getStudentCompetencies`, `getClassCriteria` and `getGradingComponents` in one `Promise.all`, holding all four as local `$state` — `StudentGradesDto`, the criterios and the components are consumed as DTOs, while the competencias go through `toCompetencyLevel`. Mutations: `createScore` and `correctScore`, `assertCompetencyLevel`, `upsertConclusion`, `deleteAssessment`, `createPracticeScore` and `deletePracticeScore`. Reads `usesInternalGrading` from `lib/stores.ts`. "Añadir evidencia" is a link into `class/{classId}/evidence/new?student=&name=&course=`, so this screen files no assessment itself.

## Conventions & Constraints
- The order of the screen is competencias, then marks, then the weighted grade last and collapsed.
- Nothing on the screen derives a level: no mark and no count is summed, averaged or rolled up, and the competency card carries that sentence in Spanish under its picker.
- An evidence row lists the criterios it declares as read-only text (codes then descriptions, or "Sin criterios declarados: no dice contra qué leerla."), and the competency card lists that competencia's criterios the same way.
- The internal system is optional. With `usesInternalGrading` false the mark inputs and the `Sistema interno de la IE` card do not render. Per piece, a mark input appears for `value_scale: 'numeric'` with a non-null `max_score`; an `ordinal` piece shows a read-only `LevelBadge` or "Sin valorar". A piece filed out of the average carries a `Fuera del promedio interno` tag.
- Evidence added from here is scoped to this student: the link carries `?student=`, and the row shows a `Solo este alumno` badge. Class-wide evidence is filed from the área.
- The accordion groups by `component_code` in first-appearance order, with the header showing the component name and `N/M evaluadas`. The kind (Quiz, Tarea, Proyecto…) rides as a label on the row, so a row's kind and its section can differ.
- Deleting evidence is soft, and the confirm dialog states what survives: the notes stay in the student's history but stop being shown and stop counting in the internal weighted grade. There is no edit.
- "Añadir nota personal" and "Añadir evidencia" are separate actions. A nota personal is filed through `AddPracticeScoreDialog` and stays out of the record.
- Marks carry no weight: `EvaluationDto` has no `weight` field, and the caption under `EVIDENCIA` states that marks do not determine the nivel de logro.
- The `Sistema interno de la IE` card renders the weighted `computed_grade` as `display_value` or the rounded `normalized_value`, with the share of the course evaluated and a line naming it the school's own system rather than the official record.
- A competencia with `level === null` reads as "No desarrollada este periodo" and renders a dash; an `ordinal` piece with no letter reads "Sin valorar".
- Saving a mark is autosave on `change`: the value is parsed, clamped to `[0, max_score]`, written back into the input, and sent as a `correctScore` against the latest attempt, or a `createScore` when there is none. A 409 `already_superseded` triggers a reload, re-resolves the fresh attempt and retries once. Success toasts "Nota guardada" and reloads, with a second reload 3s later so the worker's recomputed grade lands.
- Asserting a competency level is one write per tap.
- Long competency and criterio texts wrap: `.grow{flex:1;min-width:0}` on the text, `flex-shrink:0` on badges and icons, and `align-items:flex-start` on rows whose text can wrap.
- `CompetencyCard` blocks a `final` conclusión without the "incluye recomendaciones" checkbox, mirroring the server's 422 `missing_recommendations`.
- The error state is "No se pudieron cargar las notas." over a `Reintentar` button; `reload()` after a write fails silently and keeps the last good data on screen.

## Open Questions
- Nothing in `src/` links or navigates to `/grades/[studentId]`; the route is reached by typing the URL.
