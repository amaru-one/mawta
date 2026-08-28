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
	/** Counts of asserted niveles de logro — the official record, not the
	 *  internal weighted system. */
	distribution: { code: string; count: number }[] | null;
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

/** One criterio de evaluación an assessment evidences. */
export type CriterionRefDto = {
	criterion_id: string;
	code: string | null;
	description: string;
};

/** A graded item as *evidence*. Carries no weight: under RVM 094-2020 a mark
 *  informs the teacher's judgement and never feeds a final grade. */
export type EvaluationDto = {
	assessment_id: string;
	title: string;
	kind: AssessmentKind;
	max_score: number;
	component_code: string;
	component_name: string;
	criteria: CriterionRefDto[] | null;
	attempts: AttemptDto[] | null;
};

/** The school's OPTIONAL INTERNAL weighted system — never the official
 *  record, and never a forecast. The official record is the nivel de logro
 *  per competencia (CompetencyLevelDto). */
export type ComputedGradeDto = {
	normalized_value: number;
	display_value: string | null;
	level_code: string | null;
	evaluated_weight: number;
	total_weight: number;
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

// ---- competencias y niveles de logro (RVM 094-2020 / 048-2024) ----

// The CNEB niveles de logro. Ordered C < B < A < AD, and deliberately not
// numbers: no current norm maps them onto a 0-20 mark.
export type NivelLogro = 'AD' | 'A' | 'B' | 'C';

// What a competency counts as for promotion (5.1.3 p.9-11).
export type CompetencyKind = 'area' | 'transversal' | 'adicional_area' | 'adicional_libre';

// Why a conclusión descriptiva exists. Anything but 'optional' is mandatory
// and blocks closing the period. Decided server-side, never sent by the client.
export type ConclusionRequirement = 'level_c' | 'consecutive_c' | 'inclusion_support' | 'optional';
export type ConclusionStatus = 'draft' | 'final';

// La situación final del Acta Oficial (5.1.2.1.c p.5).
export type SituacionFinal = 'PRO' | 'PER' | 'RR';

export type CompetencyLevelDto = {
	competency_id: string;
	code: string;
	name: string;
	kind: CompetencyKind;
	subject_id: string | null;
	// The asserted level — the official record. Null means the competency was
	// not developed and evaluated this period, which is valid: do NOT render
	// it as C.
	level: NivelLogro | null;
	level_id: string | null;
	asserted_at: string | null;
	conclusion_required: boolean;
	conclusion_requirement: ConclusionRequirement;
	conclusion_body: string | null;
	conclusion_status: ConclusionStatus | null;
};

export type CompetencyLevelsDto = { competencies: CompetencyLevelDto[] | null };

export type AssertCompetencyLevelDto = {
	competency_id: string;
	level: NivelLogro;
	note?: string | null;
	term_id?: string;
};

export type ConclusionCreateDto = {
	competency_id: string;
	body: string;
	// Every conclusion must carry personalised recommendations (5.1.1.3 p.7);
	// the server rejects a 'final' one that does not.
	includes_recommendations: boolean;
	status: ConclusionStatus;
	term_id?: string;
};

// ---- reporte de fin de periodo para SIAGIE ----

export type MissingConclusionDto = {
	student_id: string;
	student_name: string;
	competency_id: string;
	competency: string;
	requirement: ConclusionRequirement;
};

export type SiagieCompetencyDto = {
	competency_id: string;
	code: string;
	name: string;
	level: NivelLogro | null;
	conclusion: string | null;
	conclusion_required: boolean;
};

export type SiagieStudentDto = {
	student_id: string;
	student_code: string;
	student_name: string;
	competencies: SiagieCompetencyDto[] | null;
};

export type SiagieReportDto = {
	class_id: string;
	class_name: string;
	subject_code: string;
	area_curricular: string | null;
	term_id: string;
	term_name: string;
	term_sequence: number;
	students: SiagieStudentDto[] | null;
	// Mandatory conclusiones descriptivas still missing. While this is
	// non-empty the period is not ready to be sent.
	blocking: MissingConclusionDto[] | null;
	ready: boolean;
	notice: string;
};

// --- Criterios de evaluación ------------------------------------------------
// The criterios a teacher writes per competencia, and the level a student
// reached against each one this period. These are the *evidence* the teacher
// weighs before asserting the competency level; nothing rolls them up
// automatically, because RVM 094-2020 makes that a judgement, not an average.

export type CriterionDto = {
	criterion_id: string;
	code: string | null;
	description: string;
	sort_order: number;
	performance_standard_id: string | null;
	// This student's level for the criterio this period, when the listing is
	// scoped to a student. Null means not yet judged — do NOT render as C.
	level: NivelLogro | null;
	level_id: string | null;
};

export type CompetencyCriteriaDto = {
	competency_id: string;
	code: string;
	name: string;
	kind: CompetencyKind;
	// Empty rather than omitted when the teacher has written none yet — a
	// competencia without criterios is the thing the screen most needs to say.
	criteria: CriterionDto[] | null;
};

export type ClassCriteriaDto = { competencies: CompetencyCriteriaDto[] | null };

export type CriterionCreateDto = {
	description: string;
	code?: string | null;
	performance_standard_id?: string | null;
};

export type AssertCriterionLevelDto = {
	criterion_id: string;
	level: NivelLogro;
	note?: string | null;
	term_id?: string;
};
