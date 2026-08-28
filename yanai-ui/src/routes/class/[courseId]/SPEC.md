## Purpose
Class dashboard screen for one class: the distribution of asserted niveles de logro, session list, entry to lessons and student grades, and nav rows into the criterios de evaluación and the end-of-period SIAGIE report.

## Contents
- `+page.svelte` — loads `getClassDashboard` + `getClassSessions`, renders the "Distribución de logros" bar, session navigation, and nav rows into `criteria/` and `siagie-report/`; can start a session.

## Inputs / Outputs
Route param `courseId` (class UUID); consumes `lib/api/endpoints/classes.ts`.

## Conventions & Constraints
- Term selection defaults to the current term server-side (`term_id` query optional).
- **"Distribución de logros" counts asserted `competency_term_levels`, not computed grades.** It is a picture of the official record, so a class where nobody has been judged yet shows nothing rather than a wall of computed bands.
- Nothing predictive is shown. The at-risk list was removed with the `risk_*` tables; the dashboard reports what teachers have recorded.
- `ClassDashboardDto.progress` (per-component registration coverage) is still returned by the API but not rendered here — it was already unused before 2026-08-27, and under a criterio-based model per-*component* coverage is the wrong unit anyway.

## Change Log
- 2026-08-27: Removed the "Por atender" at-risk section and its dead CSS (`.risk-link`, `.section-head`, `.section-count`, `.index-badge`, `.list-detail.danger`) — the risk subsystem was cut. Repointed "Distribución de logros" at asserted levels (server-side change in `repo.GetClassDashboard`). Added a "Criterios de evaluación" nav row above the SIAGIE one. Also dropped the orphan `ProgressRing` import and `.ring-row` rule, dead since before this change.
- 2026-08-26: Added a "Reporte de fin de periodo" nav row (reusing the `.list-row`/`.grow`/`.chevron` pattern already used by the at-risk section) linking to the new `siagie-report/` route.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
