package repo

import (
	"context"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
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
	RawValue      *float64  `json:"raw_value"`
}

// CriterionRef names one criterio de evaluación an assessment evidences, with
// the level this student reached against it *on this evidence* — one cell of
// the evidencia × criterio grid. Null means unjudged, which is a real state
// and must never render as C.
type CriterionRef struct {
	CriterionID uuid.UUID `json:"criterion_id"`
	Code        *string   `json:"code"`
	Description string    `json:"description"`
	Level       *string   `json:"level"`
}

// EvaluationEntry is one graded item — a quiz, an exam — as *evidence*. It
// carries no weight: under RVM 094-2020 a mark informs the teacher's
// judgement of the criterios and never feeds a final grade arithmetically.
type EvaluationEntry struct {
	AssessmentID  uuid.UUID `json:"assessment_id"`
	Title         string    `json:"title"`
	Kind          string    `json:"kind"`
	MaxScore      float64   `json:"max_score"`
	ComponentCode string    `json:"component_code"`
	ComponentName string    `json:"component_name"`
	// IsPersonal is true when the assessment was created for this student
	// alone (assessments.student_id set) rather than for the whole class.
	IsPersonal bool `json:"is_personal"`
	// CountsTowardInternal is about the school's own weighted average only.
	// False never means "does not count": the criterio levels below still feed
	// the teacher's judgement of the competencia, which is the official record.
	CountsTowardInternal bool           `json:"counts_toward_internal"`
	Criteria             []CriterionRef `json:"criteria"`
	Attempts             []ScoreAttempt `json:"attempts"`
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
		select a.id, a.title, a.kind, a.max_score, gc.code, gc.name,
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
		if err := rows.Scan(&e.AssessmentID, &e.Title, &e.Kind, &e.MaxScore, &e.ComponentCode, &e.ComponentName,
			&e.IsPersonal, &e.CountsTowardInternal,
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

	// Which criterios each assessment evidences, and where this student stands
	// against each one on that evidence. Read separately rather than joined
	// above: an assessment links to zero or many criterios, and folding that
	// into the scores join would multiply the attempt rows.
	critRows, err := tx.Query(ctx, `
		select ac.assessment_id, ec.id, ec.code, ec.description, l.code
		  from assessment_criteria ac
		  join assessments a on a.id = ac.assessment_id
		  join evaluation_criteria ec on ec.id = ac.criterion_id
		  left join evaluation_criterion_scores ecs
		         on ecs.assessment_id = ac.assessment_id
		        and ecs.criterion_id = ec.id
		        and ecs.student_id = $3
		        and ecs.superseded_at is null and ecs.deleted_at is null
		  left join grade_scale_levels l on l.id = ecs.scale_level_id
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
		if err := critRows.Scan(&assessmentID, &ref.CriterionID, &ref.Code, &ref.Description, &ref.Level); err != nil {
			return resp, err
		}
		if entry, ok := byAssessment[assessmentID]; ok {
			entry.Criteria = append(entry.Criteria, ref)
		}
	}
	if err := critRows.Err(); err != nil {
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
	ClassID      uuid.UUID
	TermID       uuid.UUID
	SchemeID     uuid.UUID
	ComponentID  uuid.UUID
	TeacherID    uuid.UUID
	StudentID    *uuid.UUID
	Title        string
	Kind         string
	MaxScore     float64
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
		                          title, kind, max_score, due_at, counts_toward_internal,
		                          status, published_at, created_by_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'published', now(), $11)
		returning id
	`, a.ClassID, a.TermID, a.SchemeID, a.ComponentID, a.StudentID,
		a.Title, a.Kind, a.MaxScore, a.DueAt, a.CountsTowardInternal, a.TeacherID).Scan(&id)
	if err != nil {
		return uuid.Nil, err
	}

	if len(a.CriterionIDs) > 0 {
		if err := LinkAssessmentCriteria(ctx, tx, a.ClassID, id, a.CriterionIDs); err != nil {
			return uuid.Nil, err
		}
	}
	return id, nil
}

// LinkAssessmentCriteria records which criterios de evaluación an assessment
// evidences. Every criterio must belong to a competencia of the class's área
// — the same guard CreateCriterion applies when the criterio is written.
func LinkAssessmentCriteria(ctx context.Context, tx pgx.Tx, classID, assessmentID uuid.UUID, criterionIDs []uuid.UUID) error {
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
	AssessmentID          uuid.UUID
	StudentID             uuid.UUID
	AttemptNumber         int16
	AttemptKind           string
	MaxValue              float64
	RetakeAuthorizationID *uuid.UUID
	Status                string
	RawValue              *float64
	LateDays              int16
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
		          retake_authorization_id, status, raw_value, late_days
	`, scoreID).Scan(&old.AssessmentID, &old.StudentID, &old.AttemptNumber, &old.AttemptKind, &old.MaxValue,
		&old.RetakeAuthorizationID, &old.Status, &old.RawValue, &old.LateDays)
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
	newRawValue := old.RawValue
	if rawValue != nil {
		newRawValue = rawValue
	}
	newLateDays := old.LateDays
	if lateDays != nil {
		newLateDays = *lateDays
	}
	studentID = old.StudentID

	err = tx.QueryRow(ctx, `
		insert into scores (tenant_id, assessment_id, student_id, attempt_number, attempt_kind,
		                     retake_authorization_id, status, raw_value, max_value, late_days,
		                     source, recorded_by_id, supersedes_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, $9, 'manual', $10, $11)
		returning id, class_id, term_id
	`, old.AssessmentID, old.StudentID, old.AttemptNumber, old.AttemptKind, old.RetakeAuthorizationID,
		newStatus, newRawValue, old.MaxValue, newLateDays, teacherID, scoreID,
	).Scan(&newScoreID, &classID, &termID)
	return
}
