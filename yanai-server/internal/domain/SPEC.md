## Purpose
Mirrors the schema's text+CHECK "enums" as Go constants so kinds/statuses are never raw string literals in Go code.

## Contents
- `consts.go` — constant blocks for session status, attendance status, score status, attempt kinds, assessment kinds, voice-note status, summary status, scale kinds (`ScaleOrdinal`…), trend values (`TrendUp`/`TrendDown`/`TrendFlat`), computed-grade scope (`ScopeTermPartial`…), the single job kind (`JobKindGradeRecompute`), and the MINEDU vocabulary added in migration 00018: competency kinds (`CompetencyArea`…), situación final (`SituationPromoted`/`SituationPermanence`/`SituationRecovery` = PRO/PER/RR) with its stage, conclusión descriptiva requirement + status, and the nivel de logro codes (`LevelC`…`LevelAD`).

## Inputs / Outputs
No dependencies; imported by `repo`, `httpapi`, and `worker`.

## Conventions & Constraints
- Values must exactly match the CHECK constraints in `migrations/` — adding an enum value is a paired change (migration + here; cascade).
- Constants only; no logic in this package.

## Change Log
- 2026-08-27: Removed `JobKindTermFailureRisk`, `JobKindPromotionProjection` and the `risk_flags.status` block — `00003` dropped the risk tables and the handlers that wrote them. The severity block stays (notifications still use it) but its comment no longer claims `risk_rules`/`risk_flags` as sources. The PRO/PER/RR constants are kept: the siglas are normative (RVM 094-2020 5.1.3) even though the code that computed them was cut, and `year_final_situations` still spells them.
- 2026-08-26: Added the constants for migration 00018 (competency kinds, PRO/PER/RR, conclusion requirements, AD/A/B/C codes) and the `risk.promotion_projection` job kind. The level codes live here only as spellings — their *ordering* and every rule that read it belonged to `internal/promotion`, which was removed on 2026-08-27; nothing currently compares them, and nothing should compare them as numbers.
- 2026-08-25: Job kinds reduced to `JobKindGradeRecompute` + new `JobKindTermFailureRisk`; removed `JobKindRiskDetect`, `JobKindNotificationSweep`, `JobKindRetentionSweep`, `JobKindNoteSummaryGenerate` with their handlers. Note the summary/voice-note *status* constants stay — those tables and their columns are untouched.
- 2026-08-24: Initial spec created retroactively, describing current contents.

## Open Questions
- None.
