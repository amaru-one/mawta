## Purpose
Mirrors the schema's text+CHECK "enums" as Go constants so kinds/statuses are never raw string literals in Go code.

## Contents
- `consts.go` — constant blocks for session status, attendance status, score status, attempt kinds, assessment kinds, voice-note status, summary status, scale kinds (`ScaleOrdinal`…), trend values (`TrendUp`/`TrendDown`/`TrendFlat`), computed-grade scope (`ScopeTermPartial`…), and job kinds (`JobKindGradeRecompute`, `JobKindRiskDetect`, `JobKindNotificationSweep`, `JobKindRetentionSweep`, `JobKindNoteSummaryGenerate`).

## Inputs / Outputs
No dependencies; imported by `repo`, `httpapi`, and `worker`.

## Conventions & Constraints
- Values must exactly match the CHECK constraints in `migrations/` — adding an enum value is a paired change (migration + here; cascade).
- Constants only; no logic in this package.

## Change Log
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
