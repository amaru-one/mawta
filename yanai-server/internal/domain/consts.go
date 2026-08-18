// Package domain mirrors the schema's text+CHECK "enums" as Go constants.
// Postgres has none of these as real enum types, so sqlc-style generation
// would give us plain strings anyway; these constants exist so call sites
// don't hand-roll the literals.
package domain

// class_sessions.status
const (
	SessionScheduled   = "scheduled"
	SessionInProgress  = "in_progress"
	SessionCompleted   = "completed"
	SessionCancelled   = "cancelled"
	SessionRescheduled = "rescheduled"
)

// attendance_records.status
const (
	AttendancePresent   = "present"
	AttendanceLate      = "late"
	AttendanceAbsent    = "absent"
	AttendanceExcused   = "excused"
	AttendanceJustified = "justified"
)

// attendance_records.source / scores.source
const (
	SourceManual = "manual"
	SourceBulk   = "bulk"
	SourceImport = "import"
	SourceVoice  = "voice"
	SourceAuto   = "auto"
)

// assessments.status
const (
	AssessmentDraft     = "draft"
	AssessmentPublished = "published"
	AssessmentClosed    = "closed"
	AssessmentCancelled = "cancelled"
)

// scores.status
const (
	ScoreGraded       = "graded"
	ScoreExcused      = "excused"
	ScoreAbsent       = "absent"
	ScoreNotSubmitted = "not_submitted"
)

// scores.attempt_kind
const (
	AttemptOriginal     = "original"
	AttemptRecuperacion = "recuperacion"
	AttemptSubsanacion  = "subsanacion"
	AttemptMakeup       = "makeup"
)

// grading_scheme_versions.retake_policy
const (
	RetakeNone   = "none"
	RetakeBest   = "best"
	RetakeLast   = "last"
	RetakeCapped = "capped"
)

// grading_scheme_versions.absent_counts_as
const (
	AbsentCountsAsZero    = "zero"
	AbsentCountsAsExcused = "excused"
)

// grading_scheme_versions.rounding_mode
const (
	RoundingHalfUp   = "half_up"
	RoundingHalfEven = "half_even"
	RoundingFloor    = "floor"
	RoundingCeil     = "ceil"
	RoundingNone     = "none"
)

// grading_scheme_component_weights.aggregation
const (
	AggregationMean         = "mean"
	AggregationWeightedMean = "weighted_mean"
	AggregationBest         = "best"
	AggregationLast         = "last"
	AggregationSum          = "sum"
)

// grade_scales.kind
const (
	ScaleOrdinal    = "ordinal"
	ScaleNumeric    = "numeric"
	ScalePercentage = "percentage"
)

// computed_grades.scope
const (
	ScopeTermPartial = "term_partial"
	ScopeTermFinal   = "term_final"
)

// computed_grades.trend
const (
	TrendUp   = "up"
	TrendDown = "down"
	TrendFlat = "flat"
)

// voice_notes.status
const (
	VoiceNoteDraft     = "draft"
	VoiceNoteSaved     = "saved"
	VoiceNoteDiscarded = "discarded"
)

// voice_notes.transcription_status
const (
	TranscriptionPending    = "pending"
	TranscriptionQueued     = "queued"
	TranscriptionProcessing = "processing"
	TranscriptionCompleted  = "completed"
	TranscriptionFailed     = "failed"
	TranscriptionSkipped    = "skipped"
)

// note_summaries.status
const (
	SummaryPending    = "pending"
	SummaryGenerating = "generating"
	SummaryReady      = "ready"
	SummaryFailed     = "failed"
	SummaryStale      = "stale"
)

// risk_flags.status
const (
	RiskFlagActive    = "active"
	RiskFlagResolved  = "resolved"
	RiskFlagDismissed = "dismissed"
	RiskFlagExpired   = "expired"
)

// notifications.kind
const (
	NotificationAlert    = "alert"
	NotificationReminder = "reminder"
)

// notifications.source
const (
	NotifSourceSystem  = "system"
	NotifSourceRule    = "rule"
	NotifSourceModel   = "model"
	NotifSourceTeacher = "teacher"
)

// jobs.status
const (
	JobAvailable = "available"
	JobRunning   = "running"
	JobRetryable = "retryable"
	JobScheduled = "scheduled"
	JobCompleted = "completed"
	JobCancelled = "cancelled"
	JobDiscarded = "discarded"
)

// jobs.kind
const (
	JobKindGradeRecompute      = "grade.recompute"
	JobKindRiskDetect          = "risk.detect"
	JobKindNotificationSweep   = "notification.sweep"
	JobKindRetentionSweep      = "retention.sweep"
	JobKindNoteSummaryGenerate = "note_summary.generate"
)

// memberships.role / status
const (
	RoleTeacher     = "teacher"
	RoleCoordinator = "coordinator"
	RoleDirector    = "director"
	RoleAdmin       = "admin"
	RoleSupport     = "support"

	MembershipActive    = "active"
	MembershipInvited   = "invited"
	MembershipSuspended = "suspended"
	MembershipRevoked   = "revoked"
)

// terms.status / academic_years.status
const (
	TermPlanned  = "planned"
	TermActive   = "active"
	TermClosed   = "closed"
	TermArchived = "archived"
)
