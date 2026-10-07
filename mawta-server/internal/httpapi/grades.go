package httpapi

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/domain"
	"mawta-server/internal/repo"
)

func (a *API) handleStudentGrades(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	studentID, err := pathUUID(r, "studentID")
	if err != nil {
		badRequest(w, "invalid studentID")
		return
	}
	termIDParam := queryUUID(r, "term_id")

	var resp repo.StudentGradesResponse
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		if err := a.requireStudentOnRoster(r.Context(), tx, tc, classID, studentID); err != nil {
			return err
		}
		term, err := repo.ResolveTerm(r.Context(), tx, classID, termIDParam)
		if err != nil {
			return err
		}
		resp, err = repo.GetStudentGrades(r.Context(), tx, classID, studentID, term.ID)
		if err != nil {
			return err
		}
		return repo.LogStudentReads(r.Context(), tx, []uuid.UUID{studentID}, tc.TeacherID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

// handleGradingComponents lists the components of the class's effective
// grading scheme — the accordion sections evidence is filed under, and the
// options in the "añadir evidencia" dialog.
func (a *API) handleGradingComponents(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	termIDParam := queryUUID(r, "term_id")

	var components []repo.GradingComponent
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		term, err := repo.ResolveTerm(r.Context(), tx, classID, termIDParam)
		if err != nil {
			return err
		}
		components, err = repo.ListGradingComponents(r.Context(), tx, classID, term.ID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"components": components})
}

// createAssessmentRequest files one piece of evidencia. StudentID set makes it
// evidence for that student alone; omitted, it is a column for the whole
// class. CriterionIDs are the criterios de evaluación it speaks to — evidence
// for the teacher's judgement, never rolled up into a level.
type createAssessmentRequest struct {
	Title         string `json:"title"`
	Kind          string `json:"kind"`
	ComponentCode string `json:"component_code"`
	// ValueScale is 'numeric' (a mark out of MaxScore, required) or 'rubric'
	// (purely qualitative — valued only through per-criterio criterion_scores,
	// MaxScore must be omitted). Omitted means numeric.
	ValueScale   string   `json:"value_scale"`
	MaxScore     *float64 `json:"max_score"`
	DueAt        *string  `json:"due_at"`
	TermID       *string  `json:"term_id"`
	StudentID    *string  `json:"student_id"`
	CriterionIDs []string `json:"criterion_ids"`
	// CountsTowardInternal defaults to true when omitted — the historical
	// behaviour, and the right one for ordinary class work. Set it false for
	// evidence that should inform the competencia but not the school's own
	// average, such as a recovery task given to one student.
	CountsTowardInternal *bool `json:"counts_toward_internal"`
}

func (a *API) handleCreateAssessment(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	var req createAssessmentRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid JSON body")
		return
	}
	if req.Title == "" || req.ComponentCode == "" {
		badRequest(w, "title and component_code are required")
		return
	}
	if req.Kind == "" {
		req.Kind = "otro"
	}
	if req.ValueScale == "" {
		req.ValueScale = domain.ValueScaleNumeric
	}
	switch req.ValueScale {
	case domain.ValueScaleNumeric:
		if req.MaxScore == nil || *req.MaxScore <= 0 {
			badRequest(w, "max_score is required and must be positive")
			return
		}
	case domain.ValueScaleRubric:
		if req.MaxScore != nil {
			badRequest(w, "max_score must be omitted for a rubric assessment")
			return
		}
	default:
		badRequest(w, "value_scale must be numeric or rubric")
		return
	}

	var termIDParam uuid.UUID
	if req.TermID != nil {
		termIDParam, _ = uuid.Parse(*req.TermID)
	}

	var studentID *uuid.UUID
	if req.StudentID != nil && *req.StudentID != "" {
		parsed, err := uuid.Parse(*req.StudentID)
		if err != nil {
			badRequest(w, "invalid student_id")
			return
		}
		studentID = &parsed
	}

	criterionIDs := make([]uuid.UUID, 0, len(req.CriterionIDs))
	for _, raw := range req.CriterionIDs {
		parsed, err := uuid.Parse(raw)
		if err != nil {
			badRequest(w, "invalid criterion_ids")
			return
		}
		criterionIDs = append(criterionIDs, parsed)
	}

	// A rubric assessment never carries a scores row (nothing to derive
	// raw_value/max_value from), so it can never count toward the school's
	// internal average — the server decides this, the same as it decides
	// descriptive_conclusions.requirement, rather than trusting the client.
	countsTowardInternal := req.CountsTowardInternal == nil || *req.CountsTowardInternal
	if req.ValueScale == domain.ValueScaleRubric {
		countsTowardInternal = false
	}

	var assessmentID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		term, err := repo.ResolveTerm(r.Context(), tx, classID, termIDParam)
		if err != nil {
			return err
		}
		scheme, err := repo.GetEffectiveScheme(r.Context(), tx, classID, term.ID)
		if err != nil {
			return err
		}
		componentID, err := repo.GetComponentIDByCode(r.Context(), tx, scheme.SchemeID, req.ComponentCode)
		if err != nil {
			return err
		}
		assessmentID, err = repo.CreateAssessment(r.Context(), tx, repo.NewAssessment{
			ClassID:      classID,
			TermID:       term.ID,
			SchemeID:     scheme.SchemeID,
			ComponentID:  componentID,
			TeacherID:    tc.TeacherID,
			StudentID:    studentID,
			Title:        req.Title,
			Kind:         req.Kind,
			ValueScale:   req.ValueScale,
			MaxScore:     req.MaxScore,
			DueAt:        req.DueAt,
			CriterionIDs: criterionIDs,

			CountsTowardInternal: countsTowardInternal,
		})
		if err != nil {
			return err
		}
		aid := assessmentID
		return repo.LogEvent(r.Context(), tx, "assessment.created", "assessment", &aid, nil, studentID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": assessmentID})
}

// handleDeleteAssessment soft-deletes a piece of evidence created by mistake.
// The scores already recorded against it stay in the student's history — the
// same rule deleted criterios follow — but the assessment stops counting
// towards the school's internal weighted grade, so every affected student is
// requeued for recompute.
func (a *API) handleDeleteAssessment(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	assessmentID, err := pathUUID(r, "assessmentID")
	if err != nil {
		badRequest(w, "invalid assessmentID")
		return
	}

	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireAssessmentAccess(r.Context(), tx, tc, assessmentID); err != nil {
			return err
		}
		d, err := repo.DeleteAssessment(r.Context(), tx, assessmentID)
		if err != nil {
			return err
		}
		aid := assessmentID
		if err := repo.LogEvent(r.Context(), tx, "assessment.deleted", "assessment",
			&aid, nil, d.StudentID, &d.ClassID, nil); err != nil {
			return err
		}

		// Class-wide evidence affects everyone currently on the roster; a
		// per-student one, only its own student.
		students := []uuid.UUID{}
		if d.StudentID != nil {
			students = append(students, *d.StudentID)
		} else {
			today, err := repo.TenantToday(r.Context(), tx, tc.TenantID)
			if err != nil {
				return err
			}
			students, err = repo.RosterAsOf(r.Context(), tx, d.ClassID, today)
			if err != nil {
				return err
			}
		}
		for _, sid := range students {
			if err := enqueueGradeRecompute(r.Context(), tx, tc.TenantID, d.ClassID, d.TermID, sid); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// createScoreRequest carries the value of one piece of work: RawValue for a
// graded assessment, nothing for a status like not_submitted.
type createScoreRequest struct {
	StudentID string   `json:"student_id"`
	Status    string   `json:"status"`
	RawValue  *float64 `json:"raw_value"`
	LateDays  int16    `json:"late_days"`
}

func (a *API) handleCreateScore(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	assessmentID, err := pathUUID(r, "assessmentID")
	if err != nil {
		badRequest(w, "invalid assessmentID")
		return
	}
	var req createScoreRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid JSON body")
		return
	}
	studentID, err := uuid.Parse(req.StudentID)
	if err != nil {
		badRequest(w, "invalid student_id")
		return
	}
	if req.Status == "" {
		req.Status = domain.ScoreGraded
	}

	var scoreID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireAssessmentAccess(r.Context(), tx, tc, assessmentID); err != nil {
			return err
		}
		var classID, termID uuid.UUID
		var err error
		scoreID, classID, termID, err = repo.CreateScore(r.Context(), tx, assessmentID, studentID, tc.TeacherID, req.Status, req.RawValue, req.LateDays)
		if err != nil {
			return err
		}
		sid := scoreID
		if err := repo.LogEvent(r.Context(), tx, "score.recorded", "score", &sid, nil, &studentID, &classID, nil); err != nil {
			return err
		}
		return enqueueGradeRecompute(r.Context(), tx, tc.TenantID, classID, termID, studentID)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": scoreID})
}

type correctScoreRequest struct {
	RawValue *float64 `json:"raw_value"`
	Status   *string  `json:"status"`
	LateDays *int16   `json:"late_days"`
}

func (a *API) handleCorrectScore(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	scoreID, err := pathUUID(r, "scoreID")
	if err != nil {
		badRequest(w, "invalid scoreID")
		return
	}
	var req correctScoreRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid JSON body")
		return
	}

	var newScoreID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireScoreAccess(r.Context(), tx, tc, scoreID); err != nil {
			return err
		}
		var studentID, classID, termID uuid.UUID
		var err error
		newScoreID, studentID, classID, termID, err = repo.CorrectScore(r.Context(), tx, scoreID, tc.TeacherID, req.RawValue, req.Status, req.LateDays)
		if err != nil {
			return err
		}
		sid := newScoreID
		if err := repo.LogEvent(r.Context(), tx, "score.corrected", "score", &sid, nil, &studentID, &classID, nil); err != nil {
			return err
		}
		return enqueueGradeRecompute(r.Context(), tx, tc.TenantID, classID, termID, studentID)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": newScoreID})
}

func enqueueGradeRecompute(ctx context.Context, tx pgx.Tx, tenantID, classID, termID, studentID uuid.UUID) error {
	payload, _ := json.Marshal(map[string]any{"class_id": classID, "term_id": termID, "student_id": studentID})
	uniqueKey := "grade.recompute:" + studentID.String() + ":" + classID.String() + ":" + termID.String()
	return repo.EnqueueJob(ctx, tx, tenantID, domain.JobKindGradeRecompute, 2, payload, uniqueKey)
}

type createCriterionScoreRequest struct {
	StudentID   string   `json:"student_id"`
	CriterionID string   `json:"criterion_id"`
	RawValue    *float64 `json:"raw_value"`
	Level       *string  `json:"level"`
}

// POST /assessments/{assessmentID}/criterion-scores
//
// One student's independent mark against one criterio within the
// assessment — a rubric line, separate from the assessment's own overall
// score.
func (a *API) handleCreateCriterionScore(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	assessmentID, err := pathUUID(r, "assessmentID")
	if err != nil {
		badRequest(w, "invalid assessmentID")
		return
	}
	var req createCriterionScoreRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid JSON body")
		return
	}
	studentID, err := uuid.Parse(req.StudentID)
	if err != nil {
		badRequest(w, "invalid student_id")
		return
	}
	criterionID, err := uuid.Parse(req.CriterionID)
	if err != nil {
		badRequest(w, "invalid criterion_id")
		return
	}

	var id uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireAssessmentAccess(r.Context(), tx, tc, assessmentID); err != nil {
			return err
		}
		var err error
		id, err = repo.CreateCriterionScore(r.Context(), tx, assessmentID, criterionID, studentID, tc.TeacherID, req.RawValue, req.Level)
		if err != nil {
			return err
		}
		cid := id
		return repo.LogEvent(r.Context(), tx, "criterion_score.recorded", "criterion_score",
			&cid, nil, &studentID, nil, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": id})
}

type correctCriterionScoreRequest struct {
	RawValue *float64 `json:"raw_value"`
	Level    *string  `json:"level"`
}

// POST /criterion-scores/{criterionScoreID}/correct
func (a *API) handleCorrectCriterionScore(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	criterionScoreID, err := pathUUID(r, "criterionScoreID")
	if err != nil {
		badRequest(w, "invalid criterionScoreID")
		return
	}
	var req correctCriterionScoreRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid JSON body")
		return
	}

	var newID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireCriterionScoreAccess(r.Context(), tx, tc, criterionScoreID); err != nil {
			return err
		}
		var err error
		newID, err = repo.CorrectCriterionScore(r.Context(), tx, criterionScoreID, tc.TeacherID, req.RawValue, req.Level)
		if err != nil {
			return err
		}
		cid := newID
		return repo.LogEvent(r.Context(), tx, "criterion_score.corrected", "criterion_score",
			&cid, nil, nil, nil, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": newID})
}
