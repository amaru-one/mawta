package httpapi

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/domain"
	"yanai-server/internal/repo"
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
		term, err := repo.ResolveTerm(r.Context(), tx, termIDParam)
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

type createAssessmentRequest struct {
	Title         string  `json:"title"`
	Kind          string  `json:"kind"`
	ComponentCode string  `json:"component_code"`
	MaxScore      float64 `json:"max_score"`
	DueAt         *string `json:"due_at"`
	TermID        *string `json:"term_id"`
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
	if req.Title == "" || req.ComponentCode == "" || req.MaxScore <= 0 {
		badRequest(w, "title, component_code and max_score are required")
		return
	}
	if req.Kind == "" {
		req.Kind = "otro"
	}

	var termIDParam uuid.UUID
	if req.TermID != nil {
		termIDParam, _ = uuid.Parse(*req.TermID)
	}

	var assessmentID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		term, err := repo.ResolveTerm(r.Context(), tx, termIDParam)
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
		assessmentID, err = repo.CreateAssessment(r.Context(), tx, classID, term.ID, scheme.SchemeID, componentID, tc.TeacherID, req.Title, req.Kind, req.MaxScore, req.DueAt)
		if err != nil {
			return err
		}
		aid := assessmentID
		return repo.LogEvent(r.Context(), tx, "assessment.created", "assessment", &aid, nil, nil, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": assessmentID})
}

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

func (a *API) handleRequestSummary(w http.ResponseWriter, r *http.Request) {
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

	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		term, err := repo.ResolveTerm(r.Context(), tx, termIDParam)
		if err != nil {
			return err
		}
		payload, _ := json.Marshal(map[string]any{
			"student_id": studentID, "class_id": classID, "term_id": term.ID, "requested_by": tc.TeacherID,
		})
		uniqueKey := "note_summary.generate:" + studentID.String() + ":" + classID.String() + ":" + term.ID.String()
		if err := repo.EnqueueJob(r.Context(), tx, tc.TenantID, domain.JobKindNoteSummaryGenerate, 2, payload, uniqueKey); err != nil {
			return err
		}
		return repo.LogEvent(r.Context(), tx, "note_summary.requested", "note_summary", nil, nil, &studentID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusAccepted, map[string]any{"status": "queued"})
}

func enqueueGradeRecompute(ctx context.Context, tx pgx.Tx, tenantID, classID, termID, studentID uuid.UUID) error {
	payload, _ := json.Marshal(map[string]any{"class_id": classID, "term_id": termID, "student_id": studentID})
	uniqueKey := "grade.recompute:" + studentID.String() + ":" + classID.String() + ":" + termID.String()
	return repo.EnqueueJob(ctx, tx, tenantID, domain.JobKindGradeRecompute, 2, payload, uniqueKey)
}
