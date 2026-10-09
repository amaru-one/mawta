// Wire types for mawta-server responses/requests, exactly as serialized:
// snake_case fields, UUID string ids, RFC3339 timestamps, "YYYY-MM-DD" dates,
// and empty lists as null (normalize with list() from ./client).

// ---- shared enums ----

export type SessionStatus = 'scheduled' | 'in_progress' | 'completed' | 'cancelled' | 'rescheduled';
export type ScoreStatus = 'graded' | 'excused' | 'absent' | 'not_submitted';
// The two kinds of evidencia the norm names (RVM 094-2020, glosario p.9),
// shared by assessments and planned evidences.
export type AssessmentKind = 'produccion' | 'actuacion';
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
	/** Counts of asserted niveles de logro — the official record. */
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

// The server still sends `attendance_status` per row and `attendance_marked` /
// `attendance_total` on the header. Nothing reads them since the lesson screen
// became a recording screen, so they are off the DTO per this folder's
// read-nowhere rule — the wire is unchanged.
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

// ---- evidence ----

/** How one piece of evidencia is valued, a property of the work itself.
 *  `numeric` is a mark out of the evidence's own `max_score`, shown as a
 *  percentage; `ordinal` is an AD/A/B/C level ON THAT WORK. Neither is a nivel
 *  de logro: the level of a competencia is asserted separately, after reading
 *  the whole period. Nothing converts between them. */
export type ValueScale = 'numeric' | 'ordinal';

/** A student's valuation of one piece of evidencia. There is one per student
 *  and evidence; a correction replaces it. */
export type ScoreDto = {
	score_id: string;
	status: ScoreStatus;
	/** Set when the evidence's `value_scale` is `numeric`. */
	raw_value: number | null;
	/** `raw_value` over `max_score`, 0–100. For display only. */
	percentage: number | null;
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

/** A piece of evidence with the student's valuation of it. Carries no weight:
 *  under RVM 094-2020 a mark informs the teacher's judgement and never feeds a
 *  final grade. */
export type EvaluationDto = {
	assessment_id: string;
	title: string;
	kind: AssessmentKind;
	value_scale: ValueScale;
	/** The denominator, present only when `value_scale` is `numeric`. */
	max_score: number | null;
	due_at: string | null;
	/** True when the assessment was created for this student alone rather than
	 *  for the whole class (`assessments.student_id`). */
	is_personal: boolean;
	criteria: CriterionRefDto[] | null;
	/** Null until the teacher values this student's work. */
	score: ScoreDto | null;
};

export type AssessmentCreateDto = {
	title: string;
	kind?: AssessmentKind;
	/** Omitted means `numeric`. */
	value_scale?: ValueScale;
	/** Required for `numeric` (any value above 0), and must be omitted for `ordinal`. */
	max_score?: number | null;
	due_at?: string | null;
	term_id?: string | null;
	/** Omitted or null files the evidence for the whole class; set, it is
	 *  evidencia for that student alone. */
	student_id?: string | null;
	/** Which criterios de evaluación the evidence speaks to — at least one: that
	 *  is how it reaches a competencia. Evidence for the teacher's judgement,
	 *  never rolled up into a nivel de logro. */
	criterion_ids: string[];
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
	// The experiencia the criterio was written for. Only the evidence-criteria
	// route sends it; a general criterio has none.
	experience_id?: string;
	experience_title?: string;
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

// ---- planning ----
// Term planning (mawta-server/docs/api-planificacion.md): a class plans each
// term as learning experiences, each with its competencies, evaluation
// criteria, planned evidences and a light session outline.

// An experience is saved step by step: it exists as 'borrador' from the first
// step and only becomes 'planificada' on confirm. Drafts already exclude each
// other's dates, so two drafts cannot take the same weeks either.
export type ExperienceStatus = 'borrador' | 'planificada';

// Computed for "Tu trimestre", never stored: 'planificada' when the
// competencia has a non-deleted experience this term; otherwise 'toca' when it
// still needs terms to be worked twice in the year and the terms left (this one
// included) are no more than it needs; 'puede_esperar' otherwise.
export type CompetencyPlanStatus = 'planificada' | 'toca' | 'puede_esperar';

// A planned evidencia has the same two kinds as the assessment it becomes.
export type EvidenceKind = AssessmentKind;

// What a background generation produces. 'experience' proposes a whole
// experience from the teacher's idea without saving it; the other three fill
// gaps inside an existing one.
export type GenerationKind = 'experience' | 'criteria' | 'evidences' | 'sessions';

export type GenerationStatus = 'pending' | 'running' | 'completed' | 'failed';

// Warnings never block; they are what the experience's summary screen shows.
export type WarningCode = 'capability_without_criterion' | 'pending_proposals';

// The contract's stable error codes (docs/api-planificacion.md, "Domain
// errors"), so each screen shows its own text instead of the server's
// message. planningErrorText (src/lib/api/planningErrors.ts) translates them.
export type DomainErrorCode =
	| 'experience_overlap'
	| 'outside_term'
	| 'competency_not_in_subject'
	| 'competency_not_in_experience'
	| 'competency_has_criteria'
	| 'capability_not_in_competency'
	| 'criterion_needs_capability'
	| 'performance_not_in_grade'
	| 'criterion_other_experience'
	| 'date_not_in_experience'
	| 'evidence_not_in_experience'
	| 'session_date_taken'
	| 'experience_not_draft'
	| 'missing_title'
	| 'missing_idea'
	| 'missing_competencies'
	| 'missing_description'
	| 'missing_name'
	| 'missing_criteria'
	| 'agent_unavailable';

// How the school's file lists a day without class. Ranges (vacaciones,
// gestion) arrive as from/to; the plan keeps the range and the calendar
// expands it into single dates.
export type NonTeachingDayKind = 'feriado' | 'vacaciones' | 'gestion';

export type PlanTermDto = {
	id: string;
	name: string;
	starts_on: string;
	ends_on: string;
	/** 'active' today; the server also marks closed terms. */
	status: string;
};

export type PlanNonTeachingDayDto = {
	from: string;
	to: string;
	kind: NonTeachingDayKind;
	label: string | null;
};

export type PlanExperienceCompetencyDto = {
	id: string;
	code: string;
	name: string;
	capabilities_total: number;
	/** Capabilities of this competencia with at least one criterio in the experience. */
	capabilities_with_criteria: number;
};

export type PlanExperienceDto = {
	id: string;
	title: string;
	status: ExperienceStatus;
	starts_on: string;
	ends_on: string;
	/** Distinct class dates in the experience's range, non-teaching days excluded. */
	class_dates: number;
	competencies: PlanExperienceCompetencyDto[] | null;
	/** Criteria, evidences and sessions still waiting for the teacher's review. */
	pending_proposals: number;
};

export type PlanCompetencyDto = {
	id: string;
	code: string;
	name: string;
	status: CompetencyPlanStatus;
	/** 1-based term sequence numbers in which the competencia was worked this year. */
	terms_worked: number[] | null;
	capabilities_total: number;
	/** Capabilities with at least one criterio in this term's experiences. */
	capabilities_covered_this_term: number;
};

export type ClassPlanDto = {
	term: PlanTermDto;
	non_teaching_days: PlanNonTeachingDayDto[] | null;
	/** Class dates in the whole term, non-teaching days excluded. */
	class_dates_total: number;
	experiences: PlanExperienceDto[] | null;
	/** The competencies of the class's area. */
	competencies: PlanCompetencyDto[] | null;
};

export type CurriculumGradeDto = {
	code: string;
	/** Null when the school did not give the grade its CNEB cycle. */
	cycle: string | null;
	/** The CNEB learning-standard level the cycle ends on (1–8); null without a cycle. */
	expected_level: number | null;
};

export type CurriculumCapabilityDto = {
	id: string;
	code: string;
	name: string;
};

export type CurriculumPerformanceDto = {
	id: string;
	order: number;
	text: string;
	/** "En progreso hacia" the cycle level rather than reaching it. */
	en_proceso: boolean;
	/** A hint, never an official link: which capability the desempeño feeds. */
	suggested_capability_id: string | null;
};

export type CurriculumCompetencyDto = {
	id: string;
	code: string;
	name: string;
	kind: CompetencyKind;
	capabilities: CurriculumCapabilityDto[] | null;
	/** The class's grade-level desempeños of this competencia. */
	performances: CurriculumPerformanceDto[] | null;
};

export type CurriculumDto = {
	grade: CurriculumGradeDto;
	competencies: CurriculumCompetencyDto[] | null;
};

export type CalendarNonTeachingDayDto = {
	date: string;
	kind: NonTeachingDayKind;
	label: string | null;
};

export type CalendarDto = {
	/** Class dates in the range, non-teaching days excluded. */
	class_dates: string[] | null;
	non_teaching_days: CalendarNonTeachingDayDto[] | null;
};

export type ExperienceCompetencyRefDto = {
	id: string;
	code: string;
	name: string;
};

// A criterio inside an experience: the teacher's instrument, grounded in one
// grade-level performance and looking at one or more capabilities of its
// competencia (N:M). Prefixed because the wire's plain CriterionDto is the
// school-wide criterio of the criteria screen.
export type ExperienceCriterionDto = {
	id: string;
	experience_id: string;
	competency_id: string;
	description: string;
	capability_ids: string[] | null;
	/** Always set for criteria written in the planning flow; nullable in the schema. */
	performance_id: string | null;
	/** 'mawta' while it is only a proposal the teacher has not accepted or edited yet. */
	proposed_by: string;
	accepted_at: string | null;
};

export type PlannedEvidenceDto = {
	id: string;
	experience_id: string;
	name: string;
	kind: EvidenceKind;
	/** How it will be valued once the experience is planned. */
	value_scale: ValueScale;
	/** The maximum of a `numeric` evidence; null for an `ordinal` one. */
	max_score: number | null;
	/** Criterios of this experience the evidencia speaks to, of any of its competencies. */
	criterion_ids: string[] | null;
	/** The class date whose session entry holds it, when it is placed. */
	session_date: string | null;
	proposed_by: string;
	accepted_at: string | null;
};

export type SessionOutlineDto = {
	date: string;
	title: string;
	topics: string | null;
	/** The evidencia placed in this session, if any (at most one per class date). */
	planned_evidence_id: string | null;
	proposed_by: string;
	accepted_at: string | null;
};

export type WarningDto =
	| { code: 'capability_without_criterion'; competency_id: string; capability_id: string }
	| { code: 'pending_proposals'; count: number };

export type ExperienceDto = {
	id: string;
	class_id: string;
	term_id: string;
	status: ExperienceStatus;
	title: string;
	idea_text: string;
	/** Null until a situation is written; it is optional. */
	situation_text: string | null;
	starts_on: string;
	ends_on: string;
	competencies: ExperienceCompetencyRefDto[] | null;
	criteria: ExperienceCriterionDto[] | null;
	evidences: PlannedEvidenceDto[] | null;
	sessions: SessionOutlineDto[] | null;
	/** Class dates inside the experience, non-teaching days excluded. */
	class_dates: string[] | null;
	warnings: WarningDto[] | null;
};

export type CreateExperienceBody = {
	term_id: string;
	title: string;
	idea_text: string;
	/** Optional: an experience can be saved before its situation is written. */
	situation_text?: string | null;
	starts_on: string;
	ends_on: string;
	/** At least one, of the class's area. */
	competency_ids: string[];
};

export type UpdateExperienceBody = {
	title?: string;
	/** "" clears the situation; leaving it out keeps it. */
	situation_text?: string;
	starts_on?: string;
	ends_on?: string;
	competency_ids?: string[];
};

export type CreateCriterionBody = {
	competency_id: string;
	description: string;
	/** At least one, of that competencia. */
	capability_ids: string[];
	/** A desempeño of that competencia for the class's grade. */
	performance_id: string;
};

export type UpdateCriterionBody = {
	description?: string;
	capability_ids?: string[];
	performance_id?: string;
};

export type CreateEvidenceBody = {
	name: string;
	kind: EvidenceKind;
	/** Omitted means `numeric`. */
	value_scale?: ValueScale;
	/** For `numeric`; omitted means 20. Must be omitted for `ordinal`. */
	max_score?: number | null;
	/** At least one, of this experience. */
	criterion_ids: string[];
	session_date?: string | null;
};

export type UpdateEvidenceBody = {
	name?: string;
	kind?: EvidenceKind;
	/** Switching to `ordinal` clears the maximum. */
	value_scale?: ValueScale;
	max_score?: number | null;
	criterion_ids?: string[];
	session_date?: string | null;
};

export type UpdateSessionBody = {
	title: string;
	topics?: string | null;
	planned_evidence_id?: string | null;
};

export type ExperienceProposalBody = {
	term_id: string;
	idea_text: string;
	competency_ids?: string[];
};

// What a completed 'experience' generation proposes. Not saved anywhere: the
// app shows it for review and the teacher creates the experience from it.
export type ExperienceProposalDto = {
	title: string;
	situation_text: string;
	competency_ids: string[];
	starts_on: string;
	ends_on: string;
};

// What a completed generation produced: the proposal for 'experience', or the
// ids (session dates, for 'sessions') of the rows it inserted — always pending
// proposals, proposed_by 'mawta', accepted_at null.
export type GenerationResultDto =
	| { proposal: ExperienceProposalDto }
	| { criteria_ids: string[] | null }
	| { evidence_ids: string[] | null }
	| { session_dates: string[] | null };

export type GenerationDto = {
	id: string;
	kind: GenerationKind;
	status: GenerationStatus;
	/** Present once the generation is completed. */
	result?: GenerationResultDto | null;
	/** Present when status is 'failed': a Spanish message written for the teacher. */
	error?: string | null;
};
