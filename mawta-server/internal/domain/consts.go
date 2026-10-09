// Package domain mirrors the schema's text+CHECK "enums" as Go constants.
// Postgres has none of these as real enum types, so sqlc-style generation
// would give us plain strings anyway; these constants exist so call sites
// don't hand-roll the literals.
//
// The mirror covers values Go actually passes as a query parameter, not the
// whole schema. A value embedded directly in the text of a SQL string (e.g.
// `where status in ('present','late')`) can never be substituted by a Go
// constant, so a block whose every use is like that is dead on arrival —
// deleted rather than kept as a spelling nobody can reach. A block whose
// subsystem has no Go code left goes the same way. Re-add either alongside
// the code that needs it.
package domain

// class_sessions.status
const (
	SessionScheduled   = "scheduled"
	SessionInProgress  = "in_progress"
	SessionCompleted   = "completed"
	SessionCancelled   = "cancelled"
	SessionRescheduled = "rescheduled"
)

// scores.status
const (
	ScoreGraded       = "graded"
	ScoreExcused      = "excused"
	ScoreAbsent       = "absent"
	ScoreNotSubmitted = "not_submitted"
)

// assessments.value_scale — how one piece of evidencia is valued, a property
// of the work itself. Numeric is a mark out of a maximum the teacher chooses
// (shown as a percentage); ordinal is an AD/A/B/C level on that work. Neither
// is a nivel de logro of the competencia.
const (
	ValueScaleNumeric = "numeric"
	ValueScaleOrdinal = "ordinal"
)

// assessments.kind and planned_evidences.kind — the two kinds of evidencia the
// norm names: "producciones y/o actuaciones realizadas por los estudiantes"
// (RVM 094-2020, glosario p.9). Both tables share the vocabulary, so a planned
// evidence becomes an assessment of the same kind.
const (
	EvidenceProduccion = "produccion"
	EvidenceActuacion  = "actuacion"
)

// IsEvidenceKind reports whether kind is one of the two evidencia kinds.
func IsEvidenceKind(kind string) bool {
	return kind == EvidenceProduccion || kind == EvidenceActuacion
}

// grade_scale_levels.code on the MINEDU ordinal scale. Ordered C < B < A < AD.
// These are only the wire/database spellings: nothing in the codebase compares
// them, and nothing should compare them as numbers — under RVM 094-2020 a
// nivel de logro is asserted by a teacher, never arrived at by arithmetic.
const (
	LevelC  = "C"
	LevelB  = "B"
	LevelA  = "A"
	LevelAD = "AD"
)

// grade_levels.stage
const (
	StageInicial    = "inicial"
	StagePrimaria   = "primaria"
	StageSecundaria = "secundaria"
	StageOtro       = "otro"
)

// grade_levels.cycle — meaningful only when stage = StageInicial.
const (
	CycleI  = "ciclo_i"
	CycleII = "ciclo_ii"
)

// descriptive_conclusions.requirement — why a conclusión descriptiva exists.
// Everything but ConclusionOptional is mandatory and blocks closing a period.
// The obligatoriedad of a level-based requirement varies by nivel educativo:
// ConclusionLevelC applies in Secundaria, Primaria and Inicial Ciclo II;
// ConclusionLevelB in Primaria and Inicial Ciclo II; ConclusionLevelA only in
// Inicial Ciclo II; ConclusionCycleIMandatory covers every competencia in
// Inicial Ciclo I regardless of level.
const (
	ConclusionLevelC           = "level_c"
	ConclusionLevelB           = "level_b"
	ConclusionLevelA           = "level_a"
	ConclusionCycleIMandatory  = "cycle_i_mandatory"
	ConclusionConsecutiveC     = "consecutive_c"
	ConclusionInclusionSupport = "inclusion_support"
	ConclusionOptional         = "optional"
)

// descriptive_conclusions.status
const (
	ConclusionDraft = "draft"
	ConclusionFinal = "final"
)

// jobs.kind
const (
	JobKindVoiceNoteTranscribe = "voice_note.transcribe"
	// JobKindAgentGenerate runs one "✦ Generar con Mawta" generation
	// (agent_generations); its payload carries only the generation id.
	JobKindAgentGenerate = "agent.generate"
)

// memberships.role and user_sessions.role. Re-added 2026-09-11 for real
// authentication: unlike the block deleted 2026-08-29, Go now genuinely
// branches on these (internal/httpapi.sessionAuth's role gate) and passes
// them as query parameters (repo.CreateSession), so they are live call
// sites rather than literals embedded in SQL text.
const (
	RoleTeacher    = "teacher"
	RoleStudent    = "student"
	RoleSupervisor = "supervisor"
	RoleAdmin      = "admin"
)

// LoginEnabledRoles is the whole of the role gate on login. Adding a role
// here is the only change needed to let it log in; every other check
// (sessionAuth, handleLogin) is written against the session's role
// generically rather than against RoleTeacher specifically.
var LoginEnabledRoles = map[string]bool{
	RoleTeacher: true,
}

// user_sessions.revoked_reason
const (
	SessionRevokeLogout         = "logout"
	SessionRevokeExpired        = "expired"
	SessionRevokeIdle           = "idle"
	SessionRevokePasswordChange = "password_change"
	SessionRevokeAdmin          = "admin"
)
