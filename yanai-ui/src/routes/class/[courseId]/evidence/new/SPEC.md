## Purpose
**Nueva evidencia** — registering one evaluation: a prueba calificada, an examen de recuperación, a
tarea. For the whole class, or for one student. It replaces `AddEvidenceDialog`.

## Contents
- `+page.svelte` — a 34px title over the shared rule, a scope lede, then the form: **LA EVALUACIÓN** (título with the
  strong stroke, tipo + componente, entrega), **CÓMO SE VALORA** (a three-cell segmented block:
  `0–20` vigesimal · `AD–C` literal · `—` sin nota, plus a "Sobre" field when numeric), **QUÉ
  COMPETENCIA AYUDA A VALORAR** (the chosen competencia in a 1px block with its criterios as marker
  squares, the other competencias as hairline rows below), the "cuenta para el promedio interno"
  checkbox, and the screen's one primary action — a gradient submit — with a mono caption.

## Inputs / Outputs
Route param `courseId`. Query: `?course=` for the header; `?student=&name=` makes the evidence belong
to that student alone. Reads `getGradingComponents` + `getClassCriteria` (`Promise.all`); one
mutation, `createAssessment`, then `goto` back to the área. Reads `usesInternalGrading`.

## Conventions & Constraints
- **It became a screen because of the criterios.** Choosing the competencia and the criterios is the
  decision that makes the evidence usable afterwards — in the 360px dialog it was a 180px scroll box
  under the fold. Nothing else about the form justified a screen.
- **Nothing is uploaded.** An evidencia here is an evaluation the teacher *registers*, not a file
  they attach. There is no upload control and there is no storage behind one.
- **The criterio is a tag, not a mark.** The copy says so under the section heading and again in the
  closing note, because it is the thing that gets misread. Nothing on this screen computes or
  suggests a nivel de logro.
- **The scale belongs to the evidence, not to the app** — the same teacher runs a numeric practice and
  an unvalued exposición in the same week. It is what decides which control appears later on the
  student's screen: `numeric` sends `max_score` and nothing else may; `ordinal` and `none` send none,
  and the server forces `counts_toward_internal` off for both, since only a numeric piece has anything
  a weighted average can use.
- **A letter here is not a nivel de logro**, and the note under the selector says so when `AD–C` is
  picked. Choosing the literal scale values a piece of work; the level of the competencia is asserted
  separately, after reading the whole period.
- Switching competencia **clears the ticked criterios**: keeping them would file the evidence against
  a criterio the teacher can no longer see.
- The scope is fixed by the caller and shown as a caption, never offered as a control — which screen
  you came from is already the answer. Class work defaults into the internal average; a per-student
  piece is the recovery task, so it does not.
- Only one 1px-stroked block on the form (the chosen competencia) plus the título field. Everything
  else is a hairline. No pills anywhere.

## Open Questions
- The caption counts criterios but not students: the roster count would need a third call
  (`getClassDashboard`) for one line of text.

## Change Log
- 2026-09-04: `AD–C` is live — `assessments.value_scale` exists (`migrations/00008`), so the button is
  no longer disabled and the form sends the scale. `sin nota` stopped sending a fake `max_score: 20`:
  a non-numeric piece now carries no denominator at all. The note under the selector changed from
  "not available yet" to saying what each scale means.
- 2026-09-04: Created, replacing `lib/components/AddEvidenceDialog.svelte` for both scopes (the área
  and the grades screen). Phase 1 of the «Alumnos y evidencia» design. The dialog's "Sobre" field
  moved under the new scale control, and the criterio checkboxes became marker squares. See
  `routes/SPEC.md`.
