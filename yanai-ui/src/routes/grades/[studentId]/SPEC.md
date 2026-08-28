## Purpose
Student grades screen. Leads with the official MINEDU record — the nivel de logro per competencia, judged against the criterios de evaluación — then the marks that serve as evidence for it, then the school's optional internal weighted grade, collapsed.

## Contents
- `+page.svelte` — loads `getStudentGrades` + `getStudentCompetencies` + `getClassCriteria` (`Promise.all`), owns local `$state` for all three (this screen predates and does not follow the `mappers.ts`-only convention for `StudentGradesDto`; the competencias code does, via `toCompetencyLevel`; criterios are consumed as DTOs). Renders, in order: "NIVELES DE LOGRO POR COMPETENCIA" (a `CompetencyCard` per competency, each holding that competencia's criterios), "EVIDENCIA" (the evaluation-module accordions), the collapsed "Sistema interno de la IE" card, practice scores, and the AI summary card.

## Inputs / Outputs
Route param `studentId`; `classId`/`studentName`/`courseName` travel as query params (`?class=&name=&course=`) since no endpoint returns them and there is no other student lookup. Mutations: `createScore`/`correctScore` (with retry-on-`already_superseded`), `createPracticeScore`/`deletePracticeScore`, `requestSummary`, `assertCompetencyLevel`/`upsertConclusion`, and `assertCriterionLevel` from `lib/api/endpoints/criteria.ts`.

## Conventions & Constraints
- **Order is the argument.** Competencias first, marks second, weighted grade last and collapsed. RVM 094-2020 determines achievement from the teacher's judgement against the criterios; a layout that led with a computed number would contradict the norm no matter what the copy said.
- **Nothing on this screen derives a level.** Criterio levels are evidence and are never summed, averaged or rolled up into the competency level; the competency card says so in plain Spanish under its picker. There is no suggested level anywhere.
- Marks carry **no weight**. `EvaluationDto` has no `weight` field and the module headers show only "N/M evaluadas". The standing caption under "EVIDENCIA" states that marks do not determine the nivel de logro — that sentence is load-bearing, not decoration.
- The "Sistema interno de la IE" card is the weighted `computed_grade`, collapsed by default and labelled as the school's own system rather than the MINEDU record (D.S. 009-2006-ED art. 37.4.f). It carries no projection: the norm has no forecast grade, and the columns were dropped in `00003`.
- A competency or criterio with `level === null` means "not evaluated this period" (RVM 048-2024, 5.1.2.2 p.1) — rendered blank/dash, never as C.
- Asserting a level (competency or criterio) is autosave-instant: tap = saved, matching the rest of the app. Each save is a deliberate per-tap write, not a background sync — see `CompetencyCard`'s doc comment.
- Long CNEB competency and criterio texts are full sentences: every row follows the app's overflow idiom — `.grow{flex:1;min-width:0}` on the text, no ellipsis, `flex-shrink:0` on badges/icons, `align-items:flex-start` on rows whose text can wrap.
- A `final` conclusión descriptiva without the "incluye recomendaciones" checkbox is blocked client-side in `CompetencyCard`, mirroring the server's 422 `missing_recommendations` — the server is still the source of truth.

## Change Log
- 2026-08-27: Rebuilt around criterios de evaluación. Deleted the "RESULTADO PARCIAL" hero, the "X% del curso evaluado · falta Y%" bar and the "Rango posible al cierre" projection card; moved competencias to the top and gave each card its criterios with a `LevelPicker` apiece; renamed "EVALUACIONES" to "EVIDENCIA", dropped "Peso NN%" from every module header, dropped the per-assessment achievement percentage, and added the criterios each assessment evidences; demoted the weighted grade to a collapsed, explicitly-labelled internal-system card. Cascade: `internal/repo/grades.go`, `lib/api/dto.ts`, `lib/components/`.
- 2026-08-26: Added the "NIVELES DE LOGRO POR COMPETENCIA" section (`CompetencyCard`/`LevelPicker`). New code follows the `mappers.ts` convention (`toCompetencyLevel`); the pre-existing grades-fetch code was left as-is, not refactored.

## Open Questions
- None.
