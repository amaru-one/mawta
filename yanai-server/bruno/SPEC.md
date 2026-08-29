## Purpose
Importable API collection for manual testing with the Bruno client.

## Contents
- `yanai-api.yaml` — OpenAPI 3.0.3 spec of the whole API, tagged into folders (00 Health & Me … 08 Perfil), with every header/path/query/body example pre-filled for the seeded demo tenant (Janice Quispe's actor id).

## Inputs / Outputs
Import into Bruno (Import Collection → OpenAPI Spec). Targets `go run ./cmd/api` against the seeded local Postgres.

## Conventions & Constraints
- This file documents, it does not drive codegen. When routes change in `internal/httpapi/router.go`, update this spec too (cascade).
- Examples embed seed-stable UUIDs; a reseed keeps them valid, hand-edited data may not.

## Change Log
- 2026-08-29: Removed eight path items whose routes were deleted: `GET /classes` (search), `GET /classes/{classID}/sessions`, `GET /classes/{classID}/siagie-report`, `POST /classes/{classID}/students/{studentID}/summary`, `POST /sessions/{sessionID}/complete`, `POST /voice-notes/{voiceNoteID}/transcript`, `GET /notifications/unread-count` and `POST /notifications/{notificationID}/dismiss`. The "05 Competencias" tag description no longer mentions the end-of-period report, the observation PUT example no longer sends `participation_level`, and the header's "Jobs" note lists only `grade.recompute` (it still named two job kinds retired long ago). Cascade from `internal/httpapi/router.go`.
- 2026-08-28: Documented the evidencia × criterio change under "06 Criterios": `POST .../criterion-levels` now requires `assessment_id` (and no longer takes `term_id`), with its three new 400 codes; `GET /classes/{classID}/criteria` describes the `evidence` row and the legacy `period_level`; added `GET /assessments/{assessmentID}/criteria-grid`. Under "04 Notas", `POST /classes/{classID}/assessments` gained `counts_toward_internal`, and `/me` now documents `tenant.uses_internal_grading`.
- 2026-08-28: Documented the evidencia routes under "04 Notas": `GET /classes/{classID}/grading-components`, `POST /assessments/{assessmentID}/delete`, and the `student_id` / `criterion_ids` fields on `POST /classes/{classID}/assessments`, with the 400 codes the two guards return.
- 2026-08-27: Added the "06 Criterios" tag and its four routes (class criteria, create criterion, delete criterion, assert criterion level); "Notificaciones" and "Perfil" shifted to 07/08. Rewrote the 05 Competencias descriptions: the endpoint no longer returns a suggested level, and "04 Notas" is evidence plus the school's internal weighted system rather than "the computed suggestion".
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
