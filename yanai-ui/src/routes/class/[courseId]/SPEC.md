## Purpose
Class dashboard screen for one class: the distribution of asserted niveles de logro, session list, entry to lessons and student grades, the nav row into the criterios de evaluación, and where evidencia for the whole class is filed.

## Contents
- `+page.svelte` — loads `getClassDashboard` + `getGradingComponents` + `getClassCriteria` (`Promise.all`; the latter two feed the evidence dialog only), renders the "Distribución de logros" bar, session navigation, a nav row into `criteria/` and an "Añadir evidencia" action opening `AddEvidenceDialog` with `scope="class"`.

## Inputs / Outputs
Route param `courseId` (class UUID); consumes `lib/api/endpoints/classes.ts` and `criteria.ts`, and reads `usesInternalGrading` from `lib/stores.ts`. One mutation: `createAssessment` without `student_id`, i.e. evidence for the whole class.

## Conventions & Constraints
- Term selection defaults to the current term server-side (`term_id` query optional).
- **"Distribución de logros" counts asserted `competency_term_levels`, not computed grades.** It is a picture of the official record, so a class where nobody has been judged yet shows nothing rather than a wall of computed bands.
- **This is where class-wide work is set up, and only class-wide work.** The dashboard is the screen that speaks for the class, so filing a column every student will be graded on belongs here; anything scoped to one student belongs on that student's screen. The dialog states its scope in a caption rather than offering a picker. The screen deliberately does not refetch after filing evidence — a new piece has no levels and no marks yet, so nothing it shows would change.
- Nothing predictive is shown. The at-risk list was removed with the `risk_*` tables; the dashboard reports what teachers have recorded.
- `ClassDashboardDto.progress` (per-component registration coverage) is still returned by the API but not rendered here — it was already unused before 2026-08-27, and under a criterio-based model per-_component_ coverage is the wrong unit anyway.

## Change Log
- 2026-08-29: The "Reporte de fin de periodo" nav row is gone with the screen behind it, and "Añadir evidencia" (`AddEvidenceDialog`, `scope="class"`) took its place in the same card — that dialog had no other home once the report was deleted, and this is the screen with the class, rather than one student, in view. `load()` became a `Promise.all` of three calls to feed it. The one new rule is a `button.list-row` width/alignment override: the row acts instead of navigating, and a `<button>` does not get from this card what an `<a>` gets for free.
- 2026-08-27: Removed the "Por atender" at-risk section and its dead CSS (`.risk-link`, `.section-head`, `.section-count`, `.index-badge`, `.list-detail.danger`) — the risk subsystem was cut. Repointed "Distribución de logros" at asserted levels (server-side change in `repo.GetClassDashboard`). Added a "Criterios de evaluación" nav row above the SIAGIE one. Also dropped the orphan `ProgressRing` import and `.ring-row` rule, dead since before this change.
- 2026-08-26: Added a "Reporte de fin de periodo" nav row (reusing the `.list-row`/`.grow`/`.chevron` pattern already used by the at-risk section) linking to the new `siagie-report/` route.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
