## Purpose
Per-kind job handlers dispatched by `internal/worker`'s registry. Each runs inside one already-open transaction (tenant RLS context set by the dispatcher).

Two kinds today. The official record — the nivel de logro per competencia under RVM 094-2020 — is asserted by a teacher through the HTTP API and is never produced by a job.

## Contents
- `common.go` — package doc only (the no-import-of-worker rule and the note above). Held the shared risk plumbing until `00003` removed the predictive subsystem.
- `recompute.go` — `GradeRecompute` (`grade.recompute`): recomputes the live `term_partial` computed grade for one student or all students with live scores in a class/term. Loads scheme/policy/weights/attempts, calls `internal/grading.Compute`, skips when the `inputs_digest` (sha256 of scheme version + sorted live score ids) is unchanged, supersedes the old row, inserts `computed_grades` + `computed_grade_components`, derives trend vs. the prior row. Feeds the school's optional internal weighted system only — never the official record. Chains nothing.
- `transcribe.go` — `VoiceNoteTranscribe` (`voice_note.transcribe`): a factory, not a plain handler — it takes an `*stt.Client` and returns the plain-argument closure the registry calls, since it is the first kind needing an external dependency (see `../CLAUDE.md`). Loads the note's audio via `repo.GetVoiceNoteFile` (a note discarded before the job ran is a no-op, not an error), calls `client.Transcribe` once, and on a permanent failure (`stt.ErrPermanent`: bad audio, no API key) records `transcription_status = 'failed'` and still returns `nil` — see the Conventions bullet on why a permanent failure is not a job failure. A transient error is returned as-is so the job's normal backoff retries it. On success, writes the transcript via `repo.SetVoiceNoteTranscript`. Chains nothing.

## Inputs / Outputs
Inputs: `pgx.Tx` + job id + raw JSON payload from the registry adapter (`voice_note.transcribe` payload: `{voice_note_id}`). Outputs: rows in `computed_grades` (+ components) for the former; `voice_notes.transcript`/`.transcription_status` for the latter. No chained jobs.

## Conventions & Constraints
- Never import `worker` (import cycle). Signature: `func X(ctx, tx pgx.Tx, [jobID int64,] payload []byte) error`. A handler needing an external dependency is a factory returning that same shape — see `transcribe.go` and its wiring in `../registry.go`.
- Idempotent; one transaction — an error rolls back everything the handler wrote.
- **Nothing here reads `grade_scales.passing_value` or `grade_scale_levels.is_passing`.** Both encoded "nota 11 aprobatoria", which applied to Secundaria for the 2020 school year only (Anexo 07 of RVM 094-2020, ended by transitoria 8.3).
- **No handler may write, suggest or imply a nivel de logro.** `competency_term_levels` is written only by a teacher's explicit action in `internal/repo/competencies.go`. A job that derived one would put a computation back where the norm puts a judgement.
- **`assessments.counts_toward_internal` is filtered here and nowhere else.** It is a property of the school's own average, not of the evidence: a piece of evidence excluded from the number still carries criterio levels that feed the teacher's judgement of the competencia, which is the official record. A query anywhere else that filtered on this column would be dropping evidence from the norm's side of the app.
- **A handler returns `nil` for "processed, nothing more to do", not just for "succeeded."** `voice_note.transcribe` returns `nil` (job `completed`) on a permanent transcription failure after recording that outcome on the domain row — an error there would burn retries, each a real (possibly billable) provider call, against something retrying can never fix.
- Known gotcha (full detail in `../CLAUDE.md`): the grade digest ignores in-place scheme edits.

## Open Questions
- None.
