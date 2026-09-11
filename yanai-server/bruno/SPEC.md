## Purpose
Importable API collection for manual testing with the Bruno client.

## Contents
- `yanai-api.yaml` — OpenAPI 3.0.3 spec of the whole API, tagged into folders (00 Auth, 00 Health & Me … 08 Perfil). Security is a `cookieAuth` (`apiKey`/`cookie`/`yanai_session`) scheme applied globally, with `security: []` on `POST /auth/login` only (login is what obtains the cookie, so it can't require one).

## Inputs / Outputs
Import into Bruno (Import Collection → OpenAPI Spec). Targets `go run ./cmd/api` against a local Postgres with an account created via `cmd/useradd` — call "00 Auth / Login" first; Bruno then sends the cookie automatically on every later request.

## Conventions & Constraints
- This file documents, it does not drive codegen. When routes change in `internal/httpapi/router.go`, update this spec too (cascade).
- **Path/query example ids are illustrative, not live** — there is no seed any more, so swap in ids from your own tenant's data.

## Change Log
- 2026-09-11: Real authentication. Added the `00 Auth` tag with `POST /auth/login`/`logout`, a `cookieAuth` security scheme applied globally (login excluded via `security: []`), and removed the `X-Tenant-ID`/`X-Actor-ID` header parameters from every one of the ~30 operations that carried them. Rewrote the intro to describe the login-first flow instead of dev headers, and dropped the psql-refresh snippet that regenerated example ids from the seed. **The individual path/query example ids (class, student, session, score, voice-note, notification ids) are untouched and still read as seed data** (e.g. "Agustín Soto", "Inglés 5to B") — they are illustrative only now, flagged as such in Conventions above, not scrubbed one by one; a future pass can replace them once real fixture data exists. Cascade: `internal/httpapi/router.go`, `internal/httpapi/SPEC.md`.
- 2026-09-04: Removed the two criterio-level path items (`POST /classes/{classID}/students/{studentID}/criterion-levels` and `GET /assessments/{assessmentID}/criteria-grid`) — both routes are gone: a criterio is a tag on a piece of evidencia and is never graded. Added `GET /classes/{classID}/students` and `GET /classes/{classID}/students/{studentID}/evidence`, the two reads the evaluating screens use. `POST /classes/{classID}/assessments` documents `value_scale` (`numeric` | `ordinal` | `none`), a `max_score` that only the numeric scale may carry, and the two new 400s. Cascade from `internal/httpapi/router.go`.
- 2026-08-29: Removed the `PUT /sessions/{sessionID}/observations/{studentID}` path item — the whole per-session observation subsystem it wrote to is gone (`migrations/00007`). `GET /flag-types` was never documented here, so nothing to remove for it. Reworded the header's "Jobs" note to name only `grade.recompute`, and the intro paragraph to describe the app's screens without a fixed count. Cascade from `internal/httpapi/router.go`.
- 2026-08-29: Removed eight path items whose routes were deleted: `GET /classes` (search), `GET /classes/{classID}/sessions`, `GET /classes/{classID}/siagie-report`, `POST /classes/{classID}/students/{studentID}/summary`, `POST /sessions/{sessionID}/complete`, `POST /voice-notes/{voiceNoteID}/transcript`, `GET /notifications/unread-count` and `POST /notifications/{notificationID}/dismiss`. The "05 Competencias" tag description no longer mentions the end-of-period report, the observation PUT example no longer sends `participation_level`, and the header's "Jobs" note lists only `grade.recompute` (it still named two job kinds retired long ago). Cascade from `internal/httpapi/router.go`.
- 2026-08-28: Documented the evidencia × criterio change under "06 Criterios": `POST .../criterion-levels` now requires `assessment_id` (and no longer takes `term_id`), with its three new 400 codes; `GET /classes/{classID}/criteria` describes the `evidence` row and the legacy `period_level`; added `GET /assessments/{assessmentID}/criteria-grid`. Under "04 Notas", `POST /classes/{classID}/assessments` gained `counts_toward_internal`, and `/me` now documents `tenant.uses_internal_grading`.
- 2026-08-28: Documented the evidencia routes under "04 Notas": `GET /classes/{classID}/grading-components`, `POST /assessments/{assessmentID}/delete`, and the `student_id` / `criterion_ids` fields on `POST /classes/{classID}/assessments`, with the 400 codes the two guards return.
- 2026-08-27: Added the "06 Criterios" tag and its four routes (class criteria, create criterion, delete criterion, assert criterion level); "Notificaciones" and "Perfil" shifted to 07/08. Rewrote the 05 Competencias descriptions: the endpoint no longer returns a suggested level, and "04 Notas" is evidence plus the school's internal weighted system rather than "the computed suggestion".
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
