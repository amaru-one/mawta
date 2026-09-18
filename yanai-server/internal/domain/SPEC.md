## Purpose
Mirrors the schema's text+CHECK "enums" as Go constants so kinds/statuses are never raw string literals in Go code. The mirror covers the tables Go actually reads or writes, not the whole schema.

## Contents
- `consts.go` — constant blocks for session status, score status, scale kinds (`ScaleOrdinal`…), computed-grade scope (`ScopeTermPartial`…) and trend (`TrendUp`/`TrendDown`/`TrendFlat`), the job kinds (`JobKindGradeRecompute`, `JobKindVoiceNoteTranscribe`), the MINEDU vocabulary (conclusión descriptiva requirement + status, nivel de logro codes `LevelC`…`LevelAD`), and — since 2026-09-11 — `Role*` (`memberships.role` / `user_sessions.role`), `LoginEnabledRoles`, and `SessionRevoke*` (`user_sessions.revoked_reason`). Every block here has at least one Go call site that passes the value as a query parameter — see Conventions.

## Inputs / Outputs
No dependencies; imported by `repo`, `httpapi`, and `worker`.

## Conventions & Constraints
- Values must exactly match the CHECK constraints in `migrations/` — adding an enum value is a paired change (migration + here; cascade).
- The mirror is not exhaustive by design, and for a structural reason: a value embedded directly in the text of a SQL string (`where status in ('present','late')`) can never be substituted by a Go constant, so a block whose every use is like that is dead on arrival. A block whose subsystem has no Go code left goes the same way. Either is deleted rather than kept as a spelling nobody can reach; re-add it alongside the code that needs it. A block with even one live call site stays whole, including siblings with no reference yet — that is the mirror doing its job.
- Constants only; no logic in this package.

## Open Questions
- None.
