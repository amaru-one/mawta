// Wire types for yanai-server responses/requests, exactly as serialized:
// snake_case fields, UUID string ids, RFC3339 timestamps, "YYYY-MM-DD" dates,
// and empty lists as null (normalize with list() from ./client).

// ---- shared enums ----

export type SessionStatus = 'scheduled' | 'in_progress' | 'completed' | 'cancelled' | 'rescheduled';
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
export type NotificationKind = 'alert' | 'reminder';
// memberships.role / user_sessions.role — mirrors internal/domain/consts.go.
// Only 'teacher' can complete a login today; the other three are modelled
// for later.
export type Role = 'teacher' | 'student' | 'supervisor' | 'admin';

// ---- identity ----

export type MeDto = {
	role: Role;
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

// The server also sends `icon_key` and `is_tutoria` on every home entry; the
// agenda renders neither, so neither is declared here (see Conventions).
export type HomeTodayDto = {
	class_id: string;
	name: string;
	session_id: string | null;
	scheduled_start_at: string | null;
	scheduled_end_at: string | null;
	status: SessionStatus | null;
	room: string | null;
	topic: string | null;
};

// A dated session elsewhere in the week. Everything is present: the row exists
// because a session does, unlike a today entry for a class with none.
export type HomeWeekSessionDto = {
	class_id: string;
	name: string;
	session_id: string;
	scheduled_start_at: string;
	scheduled_end_at: string;
	status: SessionStatus;
	room: string | null;
	topic: string | null;
};

export type HomeWeekDayDto = {
	date: string;
	/** ISO-8601 weekday: 1 = Monday .. 7 = Sunday. */
	weekday: number;
	sessions: HomeWeekSessionDto[] | null;
};

export type HomeDto = {
	date: string;
	today: HomeTodayDto[] | null;
	/** The rest of the current ISO week, one entry per day that has sessions. */
	week: HomeWeekDayDto[] | null;
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
	roster_count: number;
	sessions_per_week: number;
	term_id: string;
	next_session: SessionSummaryDto | null;
	stats: {
		scored: number;
		expected: number;
		asistencia_pct: number | null;
	};
	/** Counts of asserted niveles de logro — the official record, not the
	 *  internal weighted system. */
	distribution: { code: string; count: number }[] | null;
	grades_pending: { assessment_id: string; title: string; missing: number }[] | null;
	attendance_unmarked: { session_id: string; session_date: string }[] | null;
	upcoming: SessionSummaryDto[] | null;
	past: SessionSummaryDto[] | null;
};

// ---- lesson / session roster ----

export type RosterVoiceNoteDto = {
	id: string;
	duration_ms: number;
	status: VoiceNoteStatus;
	transcript: string | null;
};

export type RosterEntryDto = {
	student_id: string;
	name: string;
	voice_notes: RosterVoiceNoteDto[] | null;
};

// The server still sends `attendance_status` per row and `section_average_code`
// / `attendance_marked` / `attendance_total` on the header. Nothing reads them
// since the lesson screen became a recording screen, so they are off the DTO
// per this folder's read-nowhere rule — the wire is unchanged.
export type SessionRosterDto = {
	header: {
		session_id: string;
		class_id: string;
		class_name: string;
		term_id: string;
		topic: string | null;
		session_date: string;
		status: SessionStatus;
	};
	roster: RosterEntryDto[] | null;
};

// ---- grades ----

/** How one piece of evidencia is valued. `ordinal` is a letter ON THAT WORK and
 *  is not a nivel de logro: the level of a competencia is asserted separately,
 *  after reading the whole period. Nothing converts between them. */
export type ValueScale = 'numeric' | 'ordinal';

export type AttemptDto = {
	score_id: string;
	attempt_number: number;
	status: ScoreStatus;
	/** Set when the assessment's `value_scale` is `numeric`. */
	raw_value: number | null;
	/** Set when it is `ordinal`. Exactly one of the two is ever non-null. */
	level: NivelLogro | null;
};

/** One criterio de evaluación a piece of evidencia is tagged with: what the
 *  teacher said to look at in this work. It carries no level — a criterio is
 *  the ruler, never the thing marked (RVM 094-2020, 5.1.1.3 p.3). */
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
	value_scale: ValueScale;
	/** The denominator, present only when `value_scale` is `numeric`. */
	max_score: number | null;
	due_at: string | null;
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
	evaluated_weight: number;
	total_weight: number;
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
	code: string;
	name: string;
};

export type GradingComponentsDto = { components: GradingComponentDto[] | null };

export type AssessmentCreateDto = {
	title: string;
	kind?: AssessmentKind;
	component_code: string;
	/** Omitted means `numeric`, which every assessment was before scales existed. */
	value_scale?: ValueScale;
	/** Required for `numeric`, and must be omitted for the other two. */
	max_score?: number | null;
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

/** The value of one piece of work: `raw_value` on a numeric assessment, `level`
 *  on a literal one, neither for a status like `not_submitted`. Sending both is
 *  rejected — a piece of work carries one value, not two readings of it. */
export type ScoreCreateDto = {
	student_id: string;
	status?: ScoreStatus;
	raw_value?: number | null;
	level?: NivelLogro | null;
};

export type ScoreCorrectDto = {
	raw_value?: number | null;
	level?: NivelLogro | null;
	status?: ScoreStatus | null;
};

// ---- notifications ----

export type NotificationDto = {
	id: string;
	kind: NotificationKind;
	category: string;
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
// The criterios a teacher writes per competencia: what evidence is read
// against, and what a piece of evidencia is tagged with when it is filed.
// Criterios are NOT graded. The only judgement recorded anywhere is the nivel
// de logro of the competencia, which the teacher asserts after reading the
// period's evidence (RVM 094-2020, 5.1.1.3 p.2-3).

export type CriterionDto = {
	criterion_id: string;
	code: string | null;
	description: string;
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

// --- The class list and one student's evidence -------------------------------

/** One row of the class list, scoped to the competencia being looked at.
 *  `level: null` means the teacher has not judged it this period — a real state
 *  (RVM 048-2024, 5.1.2.2), rendered as a dash and never as C. */
export type ClassStudentDto = {
	student_id: string;
	/** "Apellidos, Nombres", as a Peruvian register lists them. */
	full_name: string;
	level: NivelLogro | null;
	/** How much evidence stands behind the judgement. Context, never an input:
	 *  nothing is computed from the count. */
	evidence_count: number;
};

export type ClassStudentsDto = { students: ClassStudentDto[] | null };

/** The period's evidencia for one student in one competencia. Same shape as the
 *  grades screen's rows: it is the same evidence, read for a different job. */
export type StudentEvidenceDto = { evidence: EvaluationDto[] | null };

export type CriterionCreateDto = {
	description: string;
	code?: string | null;
};
