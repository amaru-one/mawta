// Wire types for yanai-server responses/requests, exactly as serialized:
// snake_case fields, UUID string ids, RFC3339 timestamps, "YYYY-MM-DD" dates,
// and empty lists as null (normalize with list() from ./client).

// ---- shared enums ----

export type SessionStatus = 'scheduled' | 'in_progress' | 'completed' | 'cancelled' | 'rescheduled';
export type AttendanceStatus = 'present' | 'late' | 'absent' | 'excused' | 'justified';
export type ScoreStatus = 'graded' | 'excused' | 'absent' | 'not_submitted';
export type AttemptKind = 'original' | 'recuperacion' | 'subsanacion' | 'makeup';
export type AssessmentKind =
	| 'quiz'
	| 'examen'
	| 'practica'
	| 'tarea'
	| 'proyecto'
	| 'exposicion'
	| 'participacion'
	| 'rubrica'
	| 'otro';
export type VoiceNoteStatus = 'draft' | 'saved' | 'discarded';
export type TranscriptionStatus =
	'pending' | 'queued' | 'processing' | 'completed' | 'failed' | 'skipped';
export type SummaryStatus = 'pending' | 'generating' | 'ready' | 'failed' | 'stale';
export type Trend = 'up' | 'down' | 'flat';
export type Severity = 'info' | 'low' | 'medium' | 'high';
export type NotificationKind = 'alert' | 'reminder';

// ---- identity ----

export type MeDto = {
	user: { display_name: string; email: string };
	teacher: { id: string; title: string | null };
	tenant: { id: string; name: string; city: string | null; timezone: string };
};

// ---- home ----

export type HomeTodayDto = {
	class_id: string;
	name: string;
	icon_key: string | null;
	is_tutoria: boolean;
	session_id: string | null;
	scheduled_start_at: string | null;
	scheduled_end_at: string | null;
	status: SessionStatus | null;
};

export type HomeWeekSlotDto = { weekday: number; starts_at: string; ends_at: string };

export type HomeWeekDto = {
	class_id: string;
	name: string;
	icon_key: string | null;
	is_tutoria: boolean;
	slots: HomeWeekSlotDto[] | null;
};

export type HomeDto = {
	date: string;
	today: HomeTodayDto[] | null;
	week: HomeWeekDto[] | null;
};

export type ClassSearchDto = { classes: { class_id: string; name: string }[] | null };

// ---- class panel ----

export type SessionSummaryDto = {
	session_id: string;
	session_date: string;
	scheduled_start_at: string;
	scheduled_end_at: string;
	topic: string | null;
	status: SessionStatus;
	present_count?: number;
	roster_count?: number;
	missing_grades?: number;
	has_comments?: boolean;
};

export type ClassDashboardDto = {
	class_id: string;
	name: string;
	is_tutoria: boolean;
	roster_count: number;
	sessions_per_week: number;
	term_id: string;
	next_session: SessionSummaryDto | null;
	stats: {
		scored: number;
		expected: number;
		asistencia_pct: number | null;
		en_riesgo: number;
	};
	progress:
		| {
				component_id: string;
				code: string;
				name: string;
				scored: number;
				expected: number;
				/** scored/expected, or null when nothing is due for the component yet. */
				pct: number | null;
		  }[]
		| null;
	distribution: { code: string; count: number }[] | null;
	at_risk: { student_id: string; name: string; reason_text: string; severity: Severity }[] | null;
	grades_pending: { assessment_id: string; title: string; missing: number }[] | null;
	attendance_unmarked: { session_id: string; session_date: string }[] | null;
	upcoming: SessionSummaryDto[] | null;
	past: SessionSummaryDto[] | null;
};

export type SessionListDto = { sessions: SessionSummaryDto[] | null };

// ---- lesson / session roster ----

export type RosterFlagDto = {
	id: string;
	code: string;
	label: string;
	severity: Severity;
	is_positive: boolean;
};

export type RosterVoiceNoteDto = {
	id: string;
	duration_ms: number;
	status: VoiceNoteStatus;
	transcription_status: TranscriptionStatus;
	transcript: string | null;
};

export type RosterEntryDto = {
	student_id: string;
	name: string;
	level_code: string | null;
	previous_level_code: string | null;
	trend: Trend | null;
	attendance_status: AttendanceStatus | null;
	participation_level: number | null;
	observation_note: string | null;
	flags: RosterFlagDto[] | null;
	voice_notes: RosterVoiceNoteDto[] | null;
};

export type SessionRosterDto = {
	header: {
		session_id: string;
		class_id: string;
		class_name: string;
		term_id: string;
		topic: string | null;
		session_date: string;
		status: SessionStatus;
		section_average_code: string | null;
		attendance_marked: number;
		attendance_total: number;
	};
	roster: RosterEntryDto[] | null;
};

export type AttendancePutDto = {
	status: AttendanceStatus;
	minutes_late?: number | null;
	note?: string | null;
};

export type ObservationPutDto = {
	participation_level: number | null;
	note: string | null;
	// Authoritative set — omitting or null clears every flag.
	flag_type_ids: string[];
};

export type FlagTypeDto = {
	id: string;
	code: string;
	label: string;
	severity: Severity;
	is_positive: boolean;
};

// ---- grades ----

export type AttemptDto = {
	score_id: string;
	attempt_number: number;
	attempt_kind: AttemptKind;
	status: ScoreStatus;
	raw_value: number | null;
};

export type EvaluationDto = {
	assessment_id: string;
	title: string;
	kind: AssessmentKind;
	max_score: number;
	weight: number;
	component_code: string;
	attempts: AttemptDto[] | null;
};

export type ComputedGradeDto = {
	normalized_value: number;
	display_value: string | null;
	level_code: string | null;
	evaluated_weight: number;
	total_weight: number;
	projected_min_normalized: number | null;
	projected_max_normalized: number | null;
	trend: Trend | null;
};

export type NoteSummaryDto = {
	id: string;
	status: SummaryStatus;
	bullets: string[];
	notes_count: number;
};

export type PracticeScoreDto = {
	id: string;
	title: string;
	kind: AssessmentKind;
	raw_value: number;
	max_value: number;
	note: string | null;
	recorded_at: string;
};

export type StudentGradesDto = {
	computed_grade: ComputedGradeDto | null;
	evaluations: EvaluationDto[] | null;
	summary: NoteSummaryDto | null;
	practice_scores: PracticeScoreDto[] | null;
};

export type AssessmentCreateDto = {
	title: string;
	kind?: AssessmentKind;
	component_code: string;
	max_score: number;
	due_at?: string | null;
	term_id?: string | null;
};

export type PracticeScoreCreateDto = {
	title: string;
	kind?: AssessmentKind;
	raw_value: number;
	max_value: number;
	note?: string | null;
};

export type ScoreCreateDto = {
	student_id: string;
	status?: ScoreStatus;
	raw_value: number | null;
	late_days?: number;
};

export type ScoreCorrectDto = {
	raw_value?: number | null;
	status?: ScoreStatus | null;
	late_days?: number | null;
};

// ---- notifications ----

export type NotificationDto = {
	id: string;
	kind: NotificationKind;
	category: string;
	severity: Severity;
	title: string;
	body: string | null;
	created_at: string;
	read_at: string | null;
	dismissed_at: string | null;
	student_name: string | null;
	class_name: string | null;
};

export type NotificationListDto = { notifications: NotificationDto[] | null };

// ---- profile ----

export type ProfileDto = {
	display_name: string;
	title: string | null;
	hired_on: string | null;
	tenant_name: string;
	tenant_city: string | null;
	top_stats: { classes: number; students: number; weekly_hours: number };
	activity: {
		clases_dictadas: number;
		asistencias_registradas: number;
		asistencias_esperadas: number;
		notas_de_voz: number;
		evaluaciones: number;
		alumnos_en_seguimiento: number;
	};
	classes_by_grade:
		| {
				grade_label: string;
				classes: { class_id: string; name: string; roster_count: number; slots_per_week: number }[];
		  }[]
		| null;
};
