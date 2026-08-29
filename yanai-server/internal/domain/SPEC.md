## Purpose
Mirrors the schema's text+CHECK "enums" as Go constants so kinds/statuses are never raw string literals in Go code. The mirror covers the tables Go actually reads or writes, not the whole schema.

## Contents
- `consts.go` — constant blocks for session status, attendance status, score/assessment status, assessment kinds, source, voice-note status, grading-scheme knobs (rounding, aggregation, `absent_counts_as`), scale kinds (`ScaleOrdinal`…), trend values (`TrendUp`/`TrendDown`/`TrendFlat`), computed-grade scope (`ScopeTermPartial`…), notification kind/source/severity, job status and the single job kind (`JobKindGradeRecompute`), memberships and roles, term status, and the MINEDU vocabulary: competency kinds (`CompetencyArea`…), conclusión descriptiva requirement + status, and the nivel de logro codes (`LevelC`…`LevelAD`).

## Inputs / Outputs
No dependencies; imported by `repo`, `httpapi`, and `worker`.

## Conventions & Constraints
- Values must exactly match the CHECK constraints in `migrations/` — adding an enum value is a paired change (migration + here; cascade).
- The mirror is not exhaustive by design. A block whose subsystem has no Go code left is deleted rather than kept as a spelling nobody can reach; re-add it alongside the code that needs it. A block for a table Go *does* touch stays whole even if some of its values have no call site yet — that is the mirror doing its job.
- Constants only; no logic in this package.

## Change Log
- 2026-08-29: Deleted six blocks whose subsystem has no Go code: `scores.attempt_kind`, `grading_scheme_versions.retake_policy`, `note_summaries.status` (the summary route was removed), `voice_notes.transcription_status` (the transcript route was removed), and both `year_final_situations` blocks — PRO/PER/RR and its stage, kept since 2026-08-27 on the argument that the siglas are normative even without code. They still are, and the tables still spell them; the argument for a Go constant nobody can reach was weaker than the cost of a mirror that drifts. Whoever restores year-end close re-adds them with the code. The Purpose and a new convention now say the mirror tracks the Go code, not the whole schema. Cascade: `internal/repo`, `internal/httpapi`.
- 2026-08-27: Removed `JobKindTermFailureRisk`, `JobKindPromotionProjection` and the `risk_flags.status` block — `00003` dropped the risk tables and the handlers that wrote them. The severity block stays (notifications still use it) but its comment no longer claims `risk_rules`/`risk_flags` as sources. The PRO/PER/RR constants are kept: the siglas are normative (RVM 094-2020 5.1.3) even though the code that computed them was cut, and `year_final_situations` still spells them.
- 2026-08-26: Added the constants for migration 00018 (competency kinds, PRO/PER/RR, conclusion requirements, AD/A/B/C codes) and the `risk.promotion_projection` job kind. The level codes live here only as spellings — their *ordering* and every rule that read it belonged to `internal/promotion`, which was removed on 2026-08-27; nothing currently compares them, and nothing should compare them as numbers.
- 2026-08-25: Job kinds reduced to `JobKindGradeRecompute` + new `JobKindTermFailureRisk`; removed `JobKindRiskDetect`, `JobKindNotificationSweep`, `JobKindRetentionSweep`, `JobKindNoteSummaryGenerate` with their handlers. Note the summary/voice-note *status* constants stay — those tables and their columns are untouched.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
