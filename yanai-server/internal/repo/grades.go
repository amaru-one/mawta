package repo

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
)

type ComputedGradeView struct {
	NormalizedValue        float64  `json:"normalized_value"`
	DisplayValue           *string  `json:"display_value"`
	LevelCode              *string  `json:"level_code"`
	EvaluatedWeight        float64  `json:"evaluated_weight"`
	TotalWeight            float64  `json:"total_weight"`
	ProjectedMinNormalized *float64 `json:"projected_min_normalized"`
	ProjectedMaxNormalized *float64 `json:"projected_max_normalized"`
	Trend                  *string  `json:"trend"`
}

type ScoreAttempt struct {
	ScoreID       uuid.UUID `json:"score_id"`
	AttemptNumber int16     `json:"attempt_number"`
	AttemptKind   string    `json:"attempt_kind"`
	Status        string    `json:"status"`
	RawValue      *float64  `json:"raw_value"`
}

type EvaluationEntry struct {
	AssessmentID  uuid.UUID      `json:"assessment_id"`
	Title         string         `json:"title"`
	Kind          string         `json:"kind"`
	MaxScore      float64        `json:"max_score"`
	Weight        float64        `json:"weight"`
	ComponentCode string         `json:"component_code"`
	Attempts      []ScoreAttempt `json:"attempts"`
}

type SummaryView struct {
	ID         uuid.UUID `json:"id"`
	Status     string    `json:"status"`
	Bullets    []string  `json:"bullets"`
	NotesCount int       `json:"notes_count"`
}

type StudentGradesResponse struct {
	ComputedGrade *ComputedGradeView `json:"computed_grade"`
	Evaluations   []EvaluationEntry  `json:"evaluations"`
	Summary       *SummaryView       `json:"summary"`
}

func GetStudentGrades(ctx context.Context, tx pgx.Tx, classID, studentID, termID uuid.UUID) (StudentGradesResponse, error) {
	var resp StudentGradesResponse

	var cg ComputedGradeView
	err := tx.QueryRow(ctx, `
		select cg.normalized_value, cg.display_value, l.code,
		       cg.evaluated_weight, cg.total_weight,
		       cg.projected_min_normalized, cg.projected_max_normalized, cg.trend
		  from computed_grades cg
		  left join grade_scale_levels l on l.id = cg.scale_level_id
		 where cg.student_id = $1 and cg.class_id = $2 and cg.term_id = $3
		   and cg.superseded_at is null and cg.deleted_at is null
	`, studentID, classID, termID).Scan(
		&cg.NormalizedValue, &cg.DisplayValue, &cg.LevelCode,
		&cg.EvaluatedWeight, &cg.TotalWeight,
		&cg.ProjectedMinNormalized, &cg.ProjectedMaxNormalized, &cg.Trend,
	)
	if err == nil {
		resp.ComputedGrade = &cg
	} else if err != pgx.ErrNoRows {
		return resp, err
	}

	rows, err := tx.Query(ctx, `
		select a.id, a.title, a.kind, a.max_score, w.weight, gc.code,
		       s.id, s.attempt_number, s.attempt_kind, s.status, s.raw_value
		  from assessments a
		  join class_effective_grading_schemes ceg on ceg.class_id = a.class_id and ceg.term_id = a.term_id
		  join grading_scheme_component_weights w on w.scheme_version_id = ceg.scheme_version_id
		                                          and w.component_id = a.component_id and w.deleted_at is null
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
		if err := rows.Scan(&e.AssessmentID, &e.Title, &e.Kind, &e.MaxScore, &e.Weight, &e.ComponentCode,
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
