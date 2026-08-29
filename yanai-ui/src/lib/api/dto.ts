// Wire types for yanai-server responses/requests, exactly as serialized:
// snake_case fields, UUID string ids, RFC3339 timestamps, "YYYY-MM-DD" dates,
// and empty lists as null (normalize with list() from ./client).

// ---- shared enums ----

export type SessionStatus = 'scheduled' | 'in_progress' | 'completed' | 'cancelled' | 'rescheduled';
export type AttendanceStatus = 'present' | 'late' | 'absent' | 'excused' | 'justified';
export type ScoreStatus = 'graded' | 'excused' | 'absent' | 'not_submitted';
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
export type Trend = 'up' | 'down' | 'flat';
export type Severity = 'info' | 'low' | 'medium' | 'high';
export type NotificationKind = 'alert' | 'reminder';

// ---- identity ----

export type MeDto = {
	user: { display_name: string; email: string };
	teacher: { id: string; title: string | null };
	tenant: {
		id: string;
		name: string;
		city: string | null;
		timezone: string;
		/** Whether the school runs its own weighted numeric system alongside the
		 *  official record (D.S. 009-2006-ED art. 37.4.f). False hides every mark
		 *  input and the computed grade; niveles de logro are unaffected, since
		 *  the official record never comes from a number either way. */
		uses_internal_grading: boolean;
	};
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
	transcript: string | null;
};

export type RosterEntryDto = {
	student_id: string;
	name: string;
	attendance_status: AttendanceStatus | null;
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
	note?: string | null;
};

export type ObservationPutDto = {
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
	status: ScoreStatus;
	raw_value: number | null;
};

/** One criterio de evaluación an assessment evidences, with the level this
 *  student reached against it *on that evidence* — one cell of the evidencia ×
 *  criterio grid. `level: null` means unjudged; never render it as C. */
export type CriterionRefDto = {
	criterion_id: string;
	code: string | null;
	description: string;
	level: NivelLogro | null;
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
	/** True when the assessment was created for this student alone rather than
	 *  for the whole class (`assessments.student_id`). */
	is_personal: boolean;
	/** Whether this evidence feeds the school's internal weighted average. It
	 *  always feeds the official judgement — the criterio levels below count
	 *  regardless, because the norm knows nothing about this flag. */
	counts_toward_internal: boolean;
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
	practice_scores: PracticeScoreDto[] | null;
};

/** One grading component of the class's effective scheme — the accordion
 *  section a piece of evidence is filed under. */
export type GradingComponentDto = {
	component_id: string;
	code: string;
	name: string;
};

export type GradingComponentsDto = { components: GradingComponentDto[] | null };

export type AssessmentCreateDto = {
	title: string;
	kind?: AssessmentKind;
	component_code: string;
	max_score: number;
	due_at?: string | null;
	term_id?: string | null;
	/** Omitted or null files the evidence for the whole class; set, it is
	 *  evidencia for that student alone. */
	student_id?: string | null;
	/** Whether this evidence feeds the school's internal weighted average.
	 *  Omit for true. False keeps it in the official judgement and out of the
	 *  school's own number — the recovery task given to one student. */
	counts_toward_internal?: boolean;
	/** Which criterios de evaluación the evidence speaks to. Evidence for the
	 *  teacher's judgement — never rolled up into a nivel de logro. */
	criterion_ids?: string[];
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

export type CompetencyLevelDto = {
	competency_id: string;
	code: string;
	name: string;
	kind: CompetencyKind;
	// The asserted level — the official record. Null means the competency was
	// not developed and evaluated this period, which is valid: do NOT render
	// it as C.
	level: NivelLogro | null;
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

// --- Criterios de evaluación ------------------------------------------------
// The criterios a teacher writes per competencia, and the level a student
// reached against each one this period. These are the *evidence* the teacher
// weighs before asserting the competency level; nothing rolls them up
// automatically, because RVM 094-2020 makes that a judgement, not an average.

/** One cell of the evidencia × criterio grid: what this student showed against
 *  one criterio, on one piece of evidence. */
export type CriterionEvidenceDto = {
	assessment_id: string;
	title: string;
	kind: AssessmentKind;
	due_at: string | null;
	is_personal: boolean;
	level: NivelLogro;
};

export type CriterionDto = {
	criterion_id: string;
	code: string | null;
	description: string;
	performance_standard_id: string | null;
	// This criterio's row across the period's evidence, oldest first, when the
	// listing is scoped to a student. Read left to right it is a trajectory —
	// C → B → A → A is a student who learned to justify — which is why the
	// criterio itself no longer carries a single level. Empty means nothing has
	// been judged against it yet: a real state, never a C.
	evidence: CriterionEvidenceDto[] | null;
	// The legacy period-grain judgement, written before 2026-08-28 when the app
	// still let a teacher grade a criterio with no evidence in hand. Read-only
	// history; there is no writer for it any more.
	period_level: NivelLogro | null;
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

// --- Evidencia × criterio grid ----------------------------------------------
// One piece of evidence across its whole roster: the criterios it declares as
// columns, the students as rows. This is the marking view — one criterio at a
// time down thirty scripts. It carries no mark: the school's numeric system is
// the other reading of the same evidence, captured on the student's screen.

export type GridCriterionDto = {
	criterion_id: string;
	code: string | null;
	description: string;
	competency_id: string;
	competency_name: string;
};

export type GridStudentDto = {
	student_id: string;
	full_name: string;
	/** criterion_id → level. A criterio absent from the map is unjudged, which
	 *  is a real state and must never render as C. */
	levels: Record<string, NivelLogro>;
};

export type AssessmentCriteriaGridDto = {
	assessment_id: string;
	title: string;
	kind: AssessmentKind;
	class_id: string;
	term_id: string;
	due_at: string | null;
	is_personal: boolean;
	criteria: GridCriterionDto[] | null;
	students: GridStudentDto[] | null;
};

export type CriterionCreateDto = {
	description: string;
	code?: string | null;
	performance_standard_id?: string | null;
};

export type AssertCriterionLevelDto = {
	criterion_id: string;
	/** Required. A criterio level always names the evidencia it was read from:
	 *  the criterio is the ruler, never the thing being marked (RVM 094-2020,
	 *  5.1.1.3 p.3). There is no term_id — the evidencia carries the periodo. */
	assessment_id: string;
	level: NivelLogro;
	note?: string | null;
};
