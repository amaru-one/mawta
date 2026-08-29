## Purpose

The evidencia × criterio grid for one piece of evidence, across the whole class: criterios down the page, students inside each, a `LevelPicker` in every cell. This is the marking view — one criterio at a time over thirty scripts, which is how the work actually gets done, rather than opening thirty student screens.

It is the class-wide half of the same capture the grades screen offers per evidence; both write the same `evaluation_criterion_scores` rows through `assertCriterionLevel`.

## Contents

- `+page.svelte` — loads `getAssessmentCriteriaGrid`, renders one card per criterio (its text, the competencia it belongs to, and an `N/M valorados` count) with a row per student. Saves per tap, patching the level into local state instead of refetching.

## Inputs / Outputs

Route params: `courseId` (the class id, used as the `classId` in the assert call and as the back destination) and `assessmentId`. Query: `?course=` carries the class name for the header, the same convention the criterios and grades screens use. Calls `getAssessmentCriteriaGrid` and `assertCriterionLevel` from `$lib/api/endpoints/criteria`. Reached from an evidence row on `routes/grades/[studentId]/`; the back arrow is `useHistory`.

## Conventions & Constraints

- **No mark on this screen, ever.** This is the official reading — evidence judged against criterios. The school's numeric system is the _other_ reading of the same evidence and is captured on the student's screen. A `/20` box beside these pickers would put a number in the teacher's eye at the exact moment they are meant to be judging against a criterio, which is the one adjacency RVM 094-2020's framing argues against. The endpoint returns no mark, and must not be extended to.
- **Nothing is derived.** The grid records cells. It does not total them, does not colour a student by their average level, and never suggests a competency level — that stays the teacher's judgement over the whole period.
- A cell with no level renders as an unselected picker, never as C: "not yet judged" and "en inicio" are different facts.
- Saving is per tap and keyed `${studentId}:${criterionId}`, so one slow save never freezes the cell beside it — a teacher goes down a column fast. The response is patched into local state rather than triggering a refetch, because a reload on every tap would make marking a class feel like waiting on a network.
- Personal evidence (`assessments.student_id` set) shows one student and says so. The server enforces this too: a level for anyone else against it is rejected as `evidence_not_for_student`.
- An evidence declaring no criterios says exactly that, rather than rendering an empty page. Without criterios there is nothing to judge it against, and the fix is on the criterios screen.

## Change Log

- 2026-08-28: Created, as the class-wide capture point for the evidencia × criterio grain. Before this the only way to record a criterio level was one student at a time, which is not how a set of exams gets marked. Cascade from `internal/repo/criteria.go` (`GetAssessmentCriterionGrid`), `internal/httpapi` (`GET /assessments/{assessmentID}/criteria-grid`), `lib/api/`.

## Open Questions

- The roster comes from the assessment's due date (today when it has none). A student who joined the class after the due date but did the work is therefore not listed. Rare enough to leave until someone hits it, and the alternative — the roster as of today — silently drops students who left, which is worse for a record.
