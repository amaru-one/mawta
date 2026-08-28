package repo

import (
	"context"
	"encoding/json"
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

// CriterionRef names one criterio de evaluación an assessment evidences.
type CriterionRef struct {
	CriterionID uuid.UUID `json:"criterion_id"`
	Code        *string   `json:"code"`
	Description string    `json:"description"`
}

// EvaluationEntry is one graded item — a quiz, an exam — as *evidence*. It
// carries no weight: under RVM 094-2020 a mark informs the teacher's
// judgement of the criterios and never feeds a final grade arithmetically.
type EvaluationEntry struct {
	AssessmentID  uuid.UUID      `json:"assessment_id"`
	Title         string         `json:"title"`
	Kind          string         `json:"kind"`
	MaxScore      float64        `json:"max_score"`
	ComponentCode string         `json:"component_code"`
	ComponentName string         `json:"component_name"`
	Criteria      []CriterionRef `json:"criteria"`
	Attempts      []ScoreAttempt `json:"attempts"`
}

type SummaryView struct {
	ID         uuid.UUID `json:"id"`
	Status     string    `json:"status"`
	Bullets    []string  `json:"bullets"`
	NotesCount int       `json:"notes_count"`
}

type StudentGradesResponse struct {
	ComputedGrade  *ComputedGradeView   `json:"computed_grade"`
	Evaluations    []EvaluationEntry    `json:"evaluations"`
	Summary        *SummaryView         `json:"summary"`
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
		       s.id, s.attempt_number, s.attempt_kind, s.status, s.raw_value
		  from assessments a
		  join grading_components gc on gc.id = a.component_id
		  left join scores s on s.assessment_id = a.id and s.student_id = $2
		                     and s.superseded_at is null and s.deleted_at is null
		 where a.class_id = $1 and a.term_id = $3 and a.status = 'published' and a.deleted_at is null
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

	// Which criterios each assessment evidences. Read separately rather than
	// joined above: an assessment links to zero or many criterios, and folding
	// that into the scores join would multiply the attempt rows.
	critRows, err := tx.Query(ctx, `
		select ac.assessment_id, ec.id, ec.code, ec.description
		  from assessment_criteria ac
		  join assessments a on a.id = ac.assessment_id
		  join evaluation_criteria ec on ec.id = ac.criterion_id
		 where a.class_id = $1 and a.term_id = $2
		   and a.status = 'published' and a.deleted_at is null
		   and ac.deleted_at is null and ec.deleted_at is null
		 order by ec.sort_order, ec.code
	`, classID, termID)
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

	for _, id := range order {
		resp.Evaluations = append(resp.Evaluations, *byAssessment[id])
	}

	var sv SummaryView
	var bullets []byte
	err = tx.QueryRow(ctx, `
		select id, status, bullets, notes_count from note_summaries
		 where student_id = $1 and class_id = $2 and term_id = $3
		   and status in ('ready','generating','stale') and deleted_at is null
		 order by created_at desc limit 1
	`, studentID, classID, termID).Scan(&sv.ID, &sv.Status, &bullets, &sv.NotesCount)
	if err == nil {
		_ = json.Unmarshal(bullets, &sv.Bullets)
		resp.Summary = &sv
	} else if err != pgx.ErrNoRows {
		return resp, err
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

func CreateAssessment(ctx context.Context, tx pgx.Tx, classID, termID, schemeID, componentID, teacherID uuid.UUID, title, kind string, maxScore float64, dueAt *string) (uuid.UUID, error) {
	var id uuid.UUID
	err := tx.QueryRow(ctx, `
		insert into assessments (tenant_id, class_id, term_id, scheme_id, component_id, title, kind,
		                          max_score, due_at, status, published_at, created_by_id)
		values (app.current_tenant_id(), $1, $2, $3, $4, $5, $6, $7, $8, 'published', now(), $9)
		returning id
	`, classID, termID, schemeID, componentID, title, kind, maxScore, dueAt, teacherID).Scan(&id)
	return id, err
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
