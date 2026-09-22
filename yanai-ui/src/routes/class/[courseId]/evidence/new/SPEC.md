## Purpose
Nueva evidencia: registering one evaluation — a prueba calificada, an examen de recuperación, a tarea — for the whole class or for one student, tagged with the competencia and criterios it speaks to.

## Contents
- `+page.svelte` — `TopBar back="/class/{courseId}" useHistory`, the title "Nueva evidencia" over the class name, a lede stating the scope, then the form:
  - **La evaluación** — `Título` with the strong stroke, `Tipo` (the nine `AssessmentKind` values with Spanish labels, defaulting to `practica`) beside `Componente` (from `getGradingComponents`, showing "Esta clase no tiene componentes configurados." when empty), and an optional `Entrega` date.
  - **Cómo se valora** — a two-cell segmented block: `0–20 / Vigesimal` for `numeric` and `AD–C / Literal` for `ordinal`. A `Sobre` number input (`step=0.01`, `min=0.01`, defaulting to `20`) follows when the scale is numeric; a note that a letter is not a nivel de logro follows when it is ordinal.
  - **Qué competencia ayuda a valorar** — the chosen competencia in a 1px block with its criterios as toggle rows carrying a marker square and `aria-pressed` (or "Esta competencia todavía no tiene criterios…"), and the other competencias below as hairline rows of code, name, criteria count and a chevron.
  - A closing note, the `Cuenta para el promedio interno del colegio` checkbox (rendered for the numeric scale), the screen's one primary action — a gradient `Guardar evidencia` — and a mono caption reading `{code} · {N} criterio(s)`. When the class has no competencias the section reads "Esta clase no tiene competencias configuradas."

## Inputs / Outputs
Route param `courseId`. `?course=` carries the class name for the header; `?student=` and `?name=` scope the evidence to one student. Reads `getGradingComponents` and `getClassCriteria` in one `Promise.all`. One mutation, `createAssessment`, followed by `goto('/class/{courseId}')`. Reads `usesInternalGrading` from `lib/stores.ts`.

## Conventions & Constraints
- Nothing is uploaded: an evidencia here is an evaluation the teacher registers, and there is no upload control.
- A criterio is a tag rather than a mark. The copy says so under the section heading and again in the closing note, and nothing on the screen computes or suggests a nivel de logro.
- The scale belongs to the evidence and decides which control appears later on the student's screen. `numeric` sends `max_score`; `ordinal` sends `null`, and the server forces `counts_toward_internal` off for it.
- With `usesInternalGrading` false an `$effect` sets the scale to `ordinal` and the `0–20 / Vigesimal` cell renders disabled.
- Switching competencia clears the ticked criterios, so a submission carries only criterios of the competencia on screen.
- The scope is fixed by the caller and rendered as a caption rather than offered as a control: the whole-class copy, or "Solo para {name}. No aparece en la lista de los demás." Class work defaults into the internal average; a per-student piece does not.
- `canSubmit` requires a non-blank title, a resolved component (`componentCode` or the first one returned), and a positive `Sobre` on the numeric scale. The payload sends a trimmed title, the effective component, the scale, `max_score` or `null`, `due_at` as `{date}T23:59:00-05:00` or `null`, `student_id`, `counts_toward_internal` and the picked `criterion_ids`.
- On success the screen toasts "Evidencia añadida para toda la clase" or "Evidencia añadida para {name}" and navigates to the área. On failure it toasts `ApiError.message` or "No se pudo añadir la evidencia".
- The form carries one 1px-stroked block, the chosen competencia, plus the título field; the rest are hairlines.
- The error state is "No se pudo cargar el formulario." over a `Reintentar` button.

## Open Questions
- The caption counts criterios but not students: a roster count would need a third call to `getClassDashboard` for one line of text.
