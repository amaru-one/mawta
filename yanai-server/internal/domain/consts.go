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

// grade_scales.kind
const (
	ScaleOrdinal    = "ordinal"
	ScaleNumeric    = "numeric"
	ScalePercentage = "percentage"
)

// assessments.value_scale — how one piece of evidencia is valued. Deliberately
// a separate vocabulary from grade_scales.kind above, which describes a scale
// the school configured; this describes what a single piece of work carries.
//
// ValueScaleOrdinal is a letter on that piece of work and is NOT a nivel de
// logro: the level of a competencia is asserted in competency_term_levels after
// reading the whole period (RVM 094-2020, 5.1.1.3 p.2-3). Nothing may convert
// between them.
const (
	ValueScaleNumeric = "numeric"
	ValueScaleOrdinal = "ordinal"
	ValueScaleNone    = "none"
)

// computed_grades.scope
const (
	ScopeTermPartial = "term_partial"
	ScopeTermFinal   = "term_final"
)

// voice_notes.status
const (
	VoiceNoteDraft     = "draft"
	VoiceNoteSaved     = "saved"
	VoiceNoteDiscarded = "discarded"
)

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

// descriptive_conclusions.requirement — why a conclusión descriptiva exists.
// Everything but ConclusionOptional is mandatory and blocks closing a period.
const (
	ConclusionLevelC           = "level_c"
	ConclusionConsecutiveC     = "consecutive_c"
	ConclusionInclusionSupport = "inclusion_support"
	ConclusionOptional         = "optional"
)

// descriptive_conclusions.status
const (
	ConclusionDraft = "draft"
	ConclusionFinal = "final"
)

// computed_grades.trend
const (
	TrendUp   = "up"
	TrendDown = "down"
	TrendFlat = "flat"
)

// jobs.kind
const (
	JobKindGradeRecompute = "grade.recompute"
)
