## Purpose
Student grades screen: computed grade + components, score history, unofficial practice scores, voice notes, and the AI summary card.

## Contents
- `+page.svelte` — loads `getStudentGrades` (with class/term context), renders `LevelBadge`, component breakdown, practice scores (`AddPracticeScoreDialog`), `AiSummaryCard` (requestSummary → poll), score entry/correction.

## Inputs / Outputs
Route param `studentId` plus class/term from query/state; consumes `lib/api/endpoints/grades.ts`.

## Conventions & Constraints
- Grade math is server-side; the page renders `display_value`/tier codes only.
- Score writes enqueue `grade.recompute` server-side — refresh after a beat rather than computing locally.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
