## Purpose
One student, one competencia: **read, then decide**. The evidence of the period with its values, and
under it the single judgement that reaches the official record — the nivel de logro of the
competencia (RVM 094-2020, 5.1.1.3 p.2-3). This is the screen where a teacher evaluates.

## Contents
- `+page.svelte` — name at 30px, mono sub-line, `CompetencyIndex` over this student's competencias,
  the competencia's name at 19px, then two sections: **EVIDENCIAS DEL PERIODO** (one hairline-ruled
  card per piece: title + a mono kind·date line, the criterios it is tagged with as read-only text,
  the control its scale calls for, and a "No entregó" row with a marker square) and **NIVEL DE LOGRO** (`LevelSelector`, then the
  conclusión descriptiva block: textarea, "incluye recomendaciones", *Guardar borrador* / *Marcar como
  final*).

## Inputs / Outputs
Route params `courseId`, `studentId`. `?name=` and `?course=` carry the student and class names, since
no endpoint returns them — the same convention `grades/[studentId]` uses. Reads
`getStudentCompetencies` + `getClassCriteria` (`Promise.all`), then `getStudentEvidence` for the
selected competencia — the server does the narrowing, so the screen never holds work it is not
showing, and changing competencia is a fresh read. Mutations: `createScore`/`correctScore`,
`assertCompetencyLevel`, `upsertConclusion`. Reads `usesInternalGrading` from `lib/stores.ts`.

## Conventions & Constraints
- **The order of the screen is the order of the judgement.** Evidence first, decision second, with a
  heading and extra space between them. Reversing them would put the teacher's own past answer above
  the material it is supposed to rest on.
- **There is no accordion, and it was not swapped for another gesture — the state was deleted.**
  Every evidence is open with its control in place: nothing to expand, nothing to collapse, nothing
  left half-open between visits. That is only affordable with a control compact enough to sit on
  every card at once, which is why the mark is a `ScoreRuler` and not a field or a keypad.
- **Line controls inform; the boxed control decides.** The rulers are lines with no enclosure;
  `LevelSelector` is the only element on the screen inside a 1px stroke. That hierarchy is what
  separates "I valued this work" from "I decided the official record", and it is load-bearing — do
  not box the evidence controls or unbox the level.
- **Nothing computes the level.** No suggestion, no average, no roll-up, and the copy under the
  selector says so. A criterio is rendered as text only: it says what to look at in the work, it is
  not itself graded.
- **Evidence is attributed to a competencia through its criterio tags**, server-side. A piece belongs
  here when it is tagged with at least one criterio of the selected competencia; evidence tagged with
  none belongs to no competencia and appears nowhere here — it is still listed on `grades/[studentId]`.
- **The control is chosen by the evidence, not by the screen.** `value_scale` `numeric` draws a
  `ScoreRuler` over `max_score`, `ordinal` draws a `LevelScale`, `none` draws no control and says so
  in a line — a named gap rather than one that looks broken. `usesInternalGrading` false also
  suppresses the ruler, with its own sentence, since a school with no numeric system has nothing for a
  mark to mean.
- **A letter on a piece of evidencia is not a nivel de logro.** `LevelScale` and `LevelSelector` show
  the same four letters and must stay visually distinct for that reason: the first is a line control
  on a card, the second is the one boxed control on the screen.
- "No entregó" writes `status: 'not_submitted'` with a null value and greys the ruler; untoggling it
  writes `graded` back with whatever mark was there. It is a row with a marker square, never a pill.
- Saves are per tap and patch local state instead of refetching, keyed per assessment so one slow
  write never freezes the card beside it — the idiom the criterios and evidence screens already use.
- The conclusión descriptiva is **always open**, not behind a disclosure: for a student at level C or
  with inclusion support it is mandatory, and hiding it behind a tap is how it goes unwritten. A
  `final` conclusión without recommendations is blocked client-side, mirroring the server's 422.

## Open Questions
- `CompetencyLevelDto` does not carry `includes_recommendations`, so the checkbox always starts
  unticked even when a conclusión already exists — re-saving an existing final one means re-ticking
  it. Fixing it properly means adding the field to the DTO.
- The sub-line names the class but not the periodo: no read on this screen returns a term label, only
  `term_id`. Inventing "Bimestre III" would be a lie, so it is omitted.

## Change Log
- 2026-09-04: Moved onto `GET /classes/{classID}/students/{studentID}/evidence`, which narrows by
  competencia server-side instead of the screen filtering `getStudentGrades` client-side, and the
  three scales went live: a ruler for `numeric`, `LevelScale` for `ordinal`, a named blank for `none`.
  `LevelScale` was written for this screen in the morning and deleted the same hour because
  `assessments` had no `value_scale` yet; it returns with the migration. `writeScore` now carries a
  mark or a letter and the server refuses the wrong one for the assessment's scale.
- 2026-09-04: Created. Phase 1 of the «Alumnos y evidencia» design, and the screen that carries its
  central correction: the competencia is what gets evaluated, evidence only informs it, and criterios
  are tags rather than things to grade. See `routes/SPEC.md`.
