package repo

import (
	"context"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/db"
	"mawta-server/internal/domain"
)

// ComputedGradeView is the school's optional internal weighted system, never
// the official record. RVM 094-2020 determines achievement per competencia
// from the teacher's judgement against criterios — see CompetencyLevelRow.
// Carries no projection: the norm has no notion of a forecast grade.
type ComputedGradeView struct {
	NormalizedValue float64 `json:"normalized_value"`
	DisplayValue    *string `json:"display_value"`
	LevelCode       *string `json:"level_code"`
	EvaluatedWeight float64 `json:"evaluated_weight"`
	TotalWeight     float64 `json:"total_weight"`
	Trend           *string `json:"trend"`
}

type ScoreAttempt struct {
	ScoreID       uuid.UUID `json:"score_id"`
	AttemptNumber int16     `json:"attempt_number"`
	AttemptKind   string    `json:"attempt_kind"`
	Status        string    `json:"status"`
	// The mark the teacher wrote, out of the assessment's MaxScore. Null for a
	// status like not_submitted, which carries no value at all.
	RawValue *float64 `json:"raw_value"`
}

// CriterionRef names one criterio de evaluación a piece of evidencia is tagged
// with: what the teacher set out to look at in this work. It carries no level
// and must not grow one.
type CriterionRef struct {
	CriterionID uuid.UUID `json:"criterion_id"`
	Code        *string   `json:"code"`
	Description string    `json:"description"`
}

// EvaluationEntry is one graded item — a task, an exam — as *evidence*. It
// carries no weight: under RVM 094-2020 a mark informs the teacher's
// judgement of the criterios and never feeds a final grade arithmetically.
type EvaluationEntry struct {
	AssessmentID uuid.UUID `json:"assessment_id"`
	Title        string    `json:"title"`
	Kind         string    `json:"kind"`
	// ValueScale is 'numeric' (a mark out of MaxScore, in Attempts) or
	// 'rubric' (purely qualitative — no overall mark; valued only through
	// CriterionScores below, and MaxScore is null).
	ValueScale    string     `json:"value_scale"`
	MaxScore      *float64   `json:"max_score"`
	DueAt         *time.Time `json:"due_at"`
	ComponentCode string     `json:"component_code"`
	ComponentName string     `json:"component_name"`
	// IsPersonal is true when the assessment was created for this student
	// alone (assessments.student_id set) rather than for the whole class.
	IsPersonal bool `json:"is_personal"`
	// CountsTowardInternal is about the school's own weighted average only.
	// False never means "does not count": the criterio levels below still feed
	// the teacher's judgement of the competencia, which is the official record.
	CountsTowardInternal bool                  `json:"counts_toward_internal"`
	Criteria             []CriterionRef        `json:"criteria"`
	Attempts             []ScoreAttempt        `json:"attempts"`
	CriterionScores      []CriterionScoreEntry `json:"criterion_scores"`
}

// GradingComponent is one component of the class's effective scheme, as the
// options a teacher picks from when filing a new piece of evidence.
type GradingComponent struct {
	ComponentID uuid.UUID `json:"component_id"`
	Code        string    `json:"code"`
	Name        string    `json:"name"`
}

type StudentGradesResponse struct {
	ComputedGrade  *ComputedGradeView   `json:"computed_grade"`
	Evaluations    []EvaluationEntry    `json:"evaluations"`
	PracticeScores []PracticeScoreEntry `json:"practice_scores"`
}

func GetStudentGrades(ctx context.Context, tx pgx.Tx, classID, studentID, termID uuid.UUID) (StudentGradesResponse, error) {
	var resp StudentGradesResponse

	var cg ComputedGradeView
	err := tx.QueryRow(ctx, `
		select cg.normalized_value, cg.display_value, l.code,
		       cg.evaluated_weight, cg.total_weight, cg.trend
		  from computed_grades cg
		  left join grade_scale_levels l on l.id = cg.scale_level_id
		 where cg.student_id = $1 and cg.class_id = $2 and cg.term_id = $3
		   and cg.superseded_at is null and cg.deleted_at is null
	`, studentID, classID, termID).Scan(
		&cg.NormalizedValue, &cg.DisplayValue, &cg.LevelCode,
		&cg.EvaluatedWeight, &cg.TotalWeight, &cg.Trend,
	)
	if err == nil {
		resp.ComputedGrade = &cg
	} else if err != pgx.ErrNoRows {
		return resp, err
	}

	rows, err := tx.Query(ctx, `
		select a.id, a.title, a.kind, a.value_scale, a.max_score, a.due_at, gc.code, gc.name,
		       a.student_id is not null as is_personal, a.counts_toward_internal,
		       s.id, s.attempt_number, s.attempt_kind, s.status, s.raw_value
		  from assessments a
		  join grading_components gc on gc.id = a.component_id
		  left join scores s on s.assessment_id = a.id and s.student_id = $2
		                     and s.superseded_at is null and s.deleted_at is null
		 where a.class_id = $1 and a.term_id = $3 and a.status = 'published' and a.deleted_at is null
		   and (a.student_id is null or a.student_id = $2)
		 order by a.due_at nulls last, a.title, s.attempt_number
	`, classID, studentID, termID)
	if err != nil {
		return resp, err
	}
	defer rows.Close()

	byAssessment := make(map[uuid.UUID]*EvaluationEntry)
	var order []uuid.UUID
	for rows.Next() {
		var e EvaluationEntry
		var scoreID *uuid.UUID
		var attemptNumber *int16
		var attemptKind, status *string
		var rawValue *float64
		if err := rows.Scan(&e.AssessmentID, &e.Title, &e.Kind, &e.ValueScale, &e.MaxScore, &e.DueAt,
			&e.ComponentCode, &e.ComponentName, &e.IsPersonal, &e.CountsTowardInternal,
			&scoreID, &attemptNumber, &attemptKind, &status, &rawValue); err != nil {
			return resp, err
		}
		entry, ok := byAssessment[e.AssessmentID]
		if !ok {
			entry = &e
			byAssessment[e.AssessmentID] = entry
			order = append(order, e.AssessmentID)
		}
		if scoreID != nil {
			entry.Attempts = append(entry.Attempts, ScoreAttempt{
				ScoreID: *scoreID, AttemptNumber: *attemptNumber, AttemptKind: *attemptKind,
				Status: *status, RawValue: rawValue,
			})
		}
	}
	if err := rows.Err(); err != nil {
		return resp, err
	}

	// Which criterios each assessment is tagged with — what the teacher set out
	// to look at in that work. Read separately rather than joined above: an
	// assessment links to zero or many criterios, and folding that into the
	// scores join would multiply the attempt rows.
	critRows, err := tx.Query(ctx, `
		select ac.assessment_id, ec.id, ec.code, ec.description
		  from assessment_criteria ac
		  join assessments a on a.id = ac.assessment_id
		  join evaluation_criteria ec on ec.id = ac.criterion_id
		 where a.class_id = $1 and a.term_id = $2
		   and a.status = 'published' and a.deleted_at is null
		   and (a.student_id is null or a.student_id = $3)
		   and ac.deleted_at is null and ec.deleted_at is null
		 order by ec.sort_order, ec.code
	`, classID, termID, studentID)
	if err != nil {
		return resp, err
	}
	defer critRows.Close()
	for critRows.Next() {
		var assessmentID uuid.UUID
		var ref CriterionRef
		if err := critRows.Scan(&assessmentID, &ref.CriterionID, &ref.Code, &ref.Description); err != nil {
			return resp, err
		}
		if entry, ok := byAssessment[assessmentID]; ok {
			entry.Criteria = append(entry.Criteria, ref)
		}
	}
	if err := critRows.Err(); err != nil {
		return resp, err
	}

	// The independent per-criterio marks (rubric or numeric) recorded against
	// each assessment for this student. Read separately from the scores join
	// above for the same reason: a rubric assessment carries no scores row at
	// all, so its marks would otherwise be invisible to the client.
	csRows, err := tx.Query(ctx, `
		select cs.assessment_id, cs.id, cs.criterion_id, cs.student_id, cs.value_scale,
		       cs.raw_value, cs.max_value, l.code, cs.recorded_at
		  from criterion_scores cs
		  join assessments a on a.id = cs.assessment_id
		  left join grade_scale_levels l on l.id = cs.scale_level_id
		 where a.class_id = $1 and a.term_id = $2 and cs.student_id = $3
		   and a.status = 'published' and a.deleted_at is null
		   and cs.superseded_at is null and cs.deleted_at is null
		 order by cs.recorded_at
	`, classID, termID, studentID)
	if err != nil {
		return resp, err
	}
	defer csRows.Close()
	for csRows.Next() {
		var assessmentID uuid.UUID
		var entry CriterionScoreEntry
		if err := csRows.Scan(&assessmentID, &entry.ID, &entry.CriterionID, &entry.StudentID, &entry.ValueScale,
			&entry.RawValue, &entry.MaxValue, &entry.Level, &entry.RecordedAt); err != nil {
			return resp, err
		}
		if e, ok := byAssessment[assessmentID]; ok {
			e.CriterionScores = append(e.CriterionScores, entry)
		}
	}
	if err := csRows.Err(); err != nil {
		return resp, err
	}

	for _, id := range order {
		resp.Evaluations = append(resp.Evaluations, *byAssessment[id])
	}

	practiceScores, err := listPracticeScores(ctx, tx, classID, studentID, termID)
	if err != nil {
		return resp, err
	}
	resp.PracticeScores = practiceScores

	return resp, nil
}

type EffectiveScheme struct {
	SchemeID        uuid.UUID
	SchemeVersionID uuid.UUID
}

func GetEffectiveScheme(ctx context.Context, tx pgx.Tx, classID, termID uuid.UUID) (EffectiveScheme, error) {
	var s EffectiveScheme
	err := tx.QueryRow(ctx, `
		select scheme_id, scheme_version_id
		  from class_effective_grading_schemes
		 where class_id = $1 and term_id = $2
	`, classID, termID).Scan(&s.SchemeID, &s.SchemeVersionID)
	return s, err
}

func GetComponentIDByCode(ctx context.Context, tx pgx.Tx, schemeID uuid.UUID, code string) (uuid.UUID, error) {
	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		select id from grading_components where scheme_id = $1 and code = $2 and deleted_at is null
	`, schemeID, code).Scan(&id)
	return id, err
}

// ListGradingComponents returns the components of the class's effective
// scheme, in the order they are meant to be shown. These are the buckets a
// piece of evidence is filed under — the accordion sections on the grades
// screen — so the picker in the "añadir evidencia" dialog reads from here
// rather than from whatever components happen to have assessments already.
func ListGradingComponents(ctx context.Context, tx pgx.Tx, classID, termID uuid.UUID) ([]GradingComponent, error) {
	rows, err := tx.Query(ctx, `
		select gc.id, gc.code, gc.name
		  from grading_components gc
		  join class_effective_grading_schemes ceg on ceg.scheme_id = gc.scheme_id
		 where ceg.class_id = $1 and ceg.term_id = $2 and gc.deleted_at is null
		 order by gc.sort_order, gc.name
	`, classID, termID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []GradingComponent
	for rows.Next() {
		var c GradingComponent
		if err := rows.Scan(&c.ComponentID, &c.Code, &c.Name); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// NewAssessment is one piece of evidence to file. StudentID nil means the
// whole class — the original and still the common case; set, the assessment
// is evidencia for that student alone (a recovery task, a re-done project).
// CriterionIDs are the criterios de evaluación the evidence speaks to; they
// are what the teacher's judgement is made against, and are never rolled up
// into a level by anything downstream.
type NewAssessment struct {
	ClassID     uuid.UUID
	TermID      uuid.UUID
	SchemeID    uuid.UUID
	ComponentID uuid.UUID
	TeacherID   uuid.UUID
	StudentID   *uuid.UUID
	Title       string
	Kind        string
	// ValueScale is 'numeric' (MaxScore required and positive) or 'rubric'
	// (MaxScore must be nil — no overall mark, valued only through
	// criterion_scores).
	ValueScale   string
	MaxScore     *float64
	DueAt        *string
	CriterionIDs []uuid.UUID
	// CountsTowardInternal feeds the school's own weighted average only. It
	// never affects the official record: a criterio level recorded against this
	// evidence counts for the competency judgement either way.
	CountsTowardInternal bool
}

func CreateAssessment(ctx context.Context, tx pgx.Tx, a NewAssessment) (uuid.UUID, error) {
	if a.StudentID != nil {
		// The student must actually be on this class's roster. Without this a
		// teacher could file evidence against a student from another section
		// by id, and it would show up on that student's screen.
		var ok bool
		if err := tx.QueryRow(ctx, `
			select exists (
			  select 1 from classes cl
			    join section_memberships sm on sm.section_id = cl.section_id
			   where cl.id = $1 and sm.student_id = $2
			     and sm.joined_on <= current_date
			     and (sm.left_on is null or sm.left_on > current_date)
			     and sm.deleted_at is null and cl.deleted_at is null
			)
		`, a.ClassID, *a.StudentID).Scan(&ok); err != nil {
			return uuid.Nil, err
		}
		if !ok {
			return uuid.Nil, db.NewAppError(http.StatusBadRequest, "student_not_in_class",
				"that student is not on this class's roster")
		}
	}

	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		insert into assessments (tenant_id, class_id, term_id, scheme_id, component_id, student_id,
		                          title, kind, value_scale, max_score, due_at, counts_toward_internal,
		                          status, published_at, created_by_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'published', now(), $12)
		returning id
	`, a.ClassID, a.TermID, a.SchemeID, a.ComponentID, a.StudentID,
		a.Title, a.Kind, a.ValueScale, a.MaxScore, a.DueAt, a.CountsTowardInternal, a.TeacherID).Scan(&id)
	if err != nil {
		return uuid.Nil, err
	}

	if len(a.CriterionIDs) > 0 {
		if err := linkAssessmentCriteria(ctx, tx, a.ClassID, id, a.CriterionIDs); err != nil {
			return uuid.Nil, err
		}
	}
	return id, nil
}

// linkAssessmentCriteria records which criterios de evaluación an assessment
// evidences. Every criterio must belong to a competencia of the class's área
// — the same guard CreateCriterion applies when the criterio is written.
func linkAssessmentCriteria(ctx context.Context, tx pgx.Tx, classID, assessmentID uuid.UUID, criterionIDs []uuid.UUID) error {
	var inClass int
	if err := tx.QueryRow(ctx, `
		select count(*)
		  from evaluation_criteria ec
		  join competencies c on c.id = ec.competency_id
		  join courses co on co.subject_id = c.subject_id
		  join classes cl on cl.course_id = co.id
		 where cl.id = $1 and ec.id = any($2::uuid[])
		   and ec.deleted_at is null and c.deleted_at is null and cl.deleted_at is null
	`, classID, criterionIDs).Scan(&inClass); err != nil {
		return err
	}
	if inClass != len(criterionIDs) {
		return db.NewAppError(http.StatusBadRequest, "criterion_not_in_class",
			"one of those criterios does not belong to this class's área")
	}

	_, err := tx.Exec(ctx, `
		insert into assessment_criteria (tenant_id, assessment_id, criterion_id)
		select app.current_tenant_id(), $1, unnest($2::uuid[])
	`, assessmentID, criterionIDs)
	return err
}

// DeleteAssessment soft-deletes a piece of evidence. The scores recorded
// against it are left alone: they stay in the student's history exactly as
// deleted criterios keep the levels recorded against them. The assessment
// stops counting towards the school's internal weighted grade, so the caller
// must recompute afterwards.
func DeleteAssessment(ctx context.Context, tx pgx.Tx, assessmentID uuid.UUID) (DeletedAssessment, error) {
	var d DeletedAssessment
	err := tx.QueryRow(ctx, `
		update assessments set deleted_at = now()
		 where id = $1 and deleted_at is null
		returning class_id, term_id, student_id
	`, assessmentID).Scan(&d.ClassID, &d.TermID, &d.StudentID)
	if err == pgx.ErrNoRows {
		return d, db.NewAppError(http.StatusNotFound, "assessment_not_found",
			"that evidence no longer exists")
	}
	return d, err
}

// DeletedAssessment is what the caller needs to recompute after a delete:
// StudentID nil means the evidence was class-wide, so every student on the
// roster is affected.
type DeletedAssessment struct {
	ClassID   uuid.UUID
	TermID    uuid.UUID
	StudentID *uuid.UUID
}

func CreateScore(ctx context.Context, tx pgx.Tx, assessmentID, studentID, teacherID uuid.UUID, status string, rawValue *float64, lateDays int16) (id, classID, termID uuid.UUID, err error) {
	// max_value comes from the assessment, so it's always the denominator the
	// score was recorded out of, even if the assessment's own max changes later.
	err = tx.QueryRow(ctx, `
		insert into scores (tenant_id, assessment_id, student_id, attempt_number, attempt_kind,
		                     status, raw_value, max_value, late_days, source, recorded_by_id)
		select app.current_tenant_id(), $1, $2, 1, 'original', $3, $4, a.max_score, $5, 'manual', $6
		  from assessments a where a.id = $1
		returning id, class_id, term_id
	`, assessmentID, studentID, status, rawValue, lateDays, teacherID).Scan(&id, &classID, &termID)
	return
}

type correctedOldScore struct {
	AssessmentID  uuid.UUID
	StudentID     uuid.UUID
	AttemptNumber int16
	AttemptKind   string
	MaxValue      *float64
	Status        string
	RawValue      *float64
	LateDays      int16
}

// CorrectScore implements the supersede protocol: it stamps superseded_at on
// the live row first, then inserts the replacement with supersedes_id set —
// in that order, in the same transaction — because scores_live_attempt_key
// is a partial unique index and cannot be deferred.
func CorrectScore(ctx context.Context, tx pgx.Tx, scoreID, teacherID uuid.UUID, rawValue *float64, status *string, lateDays *int16) (newScoreID, studentID, classID, termID uuid.UUID, err error) {
	var old correctedOldScore
	err = tx.QueryRow(ctx, `
		update scores set superseded_at = now()
		 where id = $1 and superseded_at is null and deleted_at is null
		returning assessment_id, student_id, attempt_number, attempt_kind, max_value,
		          status, raw_value, late_days
	`, scoreID).Scan(&old.AssessmentID, &old.StudentID, &old.AttemptNumber, &old.AttemptKind, &old.MaxValue,
		&old.Status, &old.RawValue, &old.LateDays)
	if err != nil {
		if err == pgx.ErrNoRows {
			err = db.NewAppError(http.StatusConflict, "already_superseded", "score already superseded; reload and try again")
		}
		return
	}

	newStatus := old.Status
	if status != nil {
		newStatus = *status
	}
	newLateDays := old.LateDays
	if lateDays != nil {
		newLateDays = *lateDays
	}
	studentID = old.StudentID

	// A correction that names no value inherits the old one.
	newRawValue := old.RawValue
	if rawValue != nil {
		newRawValue = rawValue
	}
	// not_submitted and its siblings carry no value at all; keeping the old mark
	// would leave a number on a row that says nothing was handed in.
	if newStatus != "graded" {
		newRawValue = nil
	}

	err = tx.QueryRow(ctx, `
		insert into scores (tenant_id, assessment_id, student_id, attempt_number, attempt_kind,
		                     status, raw_value, max_value,
		                     late_days, source, recorded_by_id, supersedes_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, 'manual', $9, $10)
		returning id, class_id, term_id
	`, old.AssessmentID, old.StudentID, old.AttemptNumber, old.AttemptKind,
		newStatus, newRawValue, old.MaxValue, newLateDays, teacherID, scoreID,
	).Scan(&newScoreID, &classID, &termID)
	return
}

// CriterionScoreEntry is one student's mark against one criterio within an
// assessment — the independent rubric valuation criterion_scores exists for,
// separate from the assessment's own overall score.
type CriterionScoreEntry struct {
	ID          uuid.UUID `json:"id"`
	CriterionID uuid.UUID `json:"criterion_id"`
	StudentID   uuid.UUID `json:"student_id"`
	ValueScale  string    `json:"value_scale"`
	RawValue    *float64  `json:"raw_value"`
	MaxValue    *float64  `json:"max_value"`
	Level       *string   `json:"level"`
	RecordedAt  time.Time `json:"recorded_at"`
}

// criterionValue is the value being written to criterion_scores: a number or
// a level, decided by value_scale. criterion_scores keeps the ordinal path
// scores itself no longer has, because a rubric criterio is often marked
// descriptively rather than numerically.
type criterionValue struct {
	ValueScale string
	RawValue   *float64
	LevelID    *uuid.UUID
}

func resolveCriterionValue(ctx context.Context, tx pgx.Tx, rawValue *float64, level *string) (criterionValue, error) {
	var v criterionValue
	if rawValue != nil && level != nil {
		return v, db.NewAppError(http.StatusBadRequest, "two_values",
			"a criterion score carries a mark or a level, never both")
	}
	switch {
	case rawValue != nil:
		v.ValueScale = domain.ValueScaleNumeric
		v.RawValue = rawValue
	case level != nil:
		var levelID uuid.UUID
		err := tx.QueryRow(ctx, `
			select l.id
			  from grade_scale_levels l
			  join grade_scales g on g.id = l.scale_id
			 where g.kind = 'ordinal' and l.code = $1
			   and l.deleted_at is null and g.deleted_at is null
			 limit 1
		`, *level).Scan(&levelID)
		if err != nil {
			if err == pgx.ErrNoRows {
				return v, db.NewAppError(http.StatusBadRequest, "unknown_level",
					"level must be one of AD, A, B or C")
			}
			return v, err
		}
		v.ValueScale = domain.ValueScaleOrdinal
		v.LevelID = &levelID
	default:
		return v, db.NewAppError(http.StatusBadRequest, "missing_value",
			"a criterion score needs a mark or a level")
	}
	return v, nil
}

// requireMaxScoreForNumeric guards the one case criterion_scores' derived
// max_value can't paper over: a numeric mark against a rubric assessment,
// whose max_score is null, leaves nothing to record the mark out of.
func requireMaxScoreForNumeric(ctx context.Context, tx pgx.Tx, assessmentID uuid.UUID, valueScale string) error {
	if valueScale != domain.ValueScaleNumeric {
		return nil
	}
	var hasMaxScore bool
	if err := tx.QueryRow(ctx, `select max_score is not null from assessments where id = $1`, assessmentID).Scan(&hasMaxScore); err != nil {
		return err
	}
	if !hasMaxScore {
		return db.NewAppError(http.StatusBadRequest, "no_max_score",
			"a numeric criterion score needs its assessment to carry a max_score; mark this criterio by level instead")
	}
	return nil
}

// requireAssessmentCriterionTag guards what criterion_scores_rubric_item_fk
// enforces at the DB level: a mark can only be recorded against a criterio
// the assessment was actually tagged with via assessment_criteria. Checked
// here first so the caller gets a clear 400 instead of a bare FK-violation.
func requireAssessmentCriterionTag(ctx context.Context, tx pgx.Tx, assessmentID, criterionID uuid.UUID) error {
	var tagged bool
	if err := tx.QueryRow(ctx, `
		select exists (
		  select 1 from assessment_criteria
		   where assessment_id = $1 and criterion_id = $2 and deleted_at is null
		)
	`, assessmentID, criterionID).Scan(&tagged); err != nil {
		return err
	}
	if !tagged {
		return db.NewAppError(http.StatusBadRequest, "criterion_not_tagged",
			"this criterio was never tagged on this assessment")
	}
	return nil
}

// CreateCriterionScore records a student's mark against one criterio within
// an assessment. max_value is set from the assessment only for a numeric
// value — an ordinal one has no denominator.
func CreateCriterionScore(ctx context.Context, tx pgx.Tx, assessmentID, criterionID, studentID, teacherID uuid.UUID, rawValue *float64, level *string) (id uuid.UUID, err error) {
	v, err := resolveCriterionValue(ctx, tx, rawValue, level)
	if err != nil {
		return
	}
	if err = requireMaxScoreForNumeric(ctx, tx, assessmentID, v.ValueScale); err != nil {
		return
	}
	if err = requireAssessmentCriterionTag(ctx, tx, assessmentID, criterionID); err != nil {
		return
	}
	err = tx.QueryRow(ctx, `
		insert into criterion_scores (tenant_id, assessment_id, criterion_id, student_id,
		                               value_scale, raw_value, max_value, scale_level_id, recorded_by_id)
		select app.current_tenant_id(), $1, $2, $3, $4, $5,
		       case when $4 = 'numeric' then a.max_score else null end, $6, $7
		  from assessments a where a.id = $1
		returning id
	`, assessmentID, criterionID, studentID, v.ValueScale, v.RawValue, v.LevelID, teacherID).Scan(&id)
	return
}

// CorrectCriterionScore implements the same supersede protocol as
// CorrectScore: stamp superseded_at on the live row, then insert the
// replacement with supersedes_id set.
func CorrectCriterionScore(ctx context.Context, tx pgx.Tx, criterionScoreID, teacherID uuid.UUID, rawValue *float64, level *string) (newID uuid.UUID, err error) {
	v, err := resolveCriterionValue(ctx, tx, rawValue, level)
	if err != nil {
		return
	}

	var assessmentID, criterionID, studentID uuid.UUID
	err = tx.QueryRow(ctx, `
		update criterion_scores set superseded_at = now()
		 where id = $1 and superseded_at is null and deleted_at is null
		returning assessment_id, criterion_id, student_id
	`, criterionScoreID).Scan(&assessmentID, &criterionID, &studentID)
	if err != nil {
		if err == pgx.ErrNoRows {
			err = db.NewAppError(http.StatusConflict, "already_superseded",
				"criterion score already superseded; reload and try again")
		}
		return
	}
	if err = requireMaxScoreForNumeric(ctx, tx, assessmentID, v.ValueScale); err != nil {
		return
	}
	if err = requireAssessmentCriterionTag(ctx, tx, assessmentID, criterionID); err != nil {
		return
	}

	err = tx.QueryRow(ctx, `
		insert into criterion_scores (tenant_id, assessment_id, criterion_id, student_id,
		                               value_scale, raw_value, max_value, scale_level_id,
		                               recorded_by_id, supersedes_id)
		select app.current_tenant_id(), $1, $2, $3, $4, $5,
		       case when $4 = 'numeric' then a.max_score else null end, $6, $7, $8
		  from assessments a where a.id = $1
		returning id
	`, assessmentID, criterionID, studentID, v.ValueScale, v.RawValue, v.LevelID, teacherID, criterionScoreID).Scan(&newID)
	return
}
