package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/domain"
	"mawta-server/internal/repo"
)

// createAssessmentRequest files one piece of evidencia. StudentID set makes it
// evidence for that student alone; omitted, it is a column for the whole
// class. CriterionIDs are the criterios de evaluación it speaks to — at least
// one is required, since that is how the evidence reaches a competencia — and
// they are evidence for the teacher's judgement, never rolled up into a level.
type createAssessmentRequest struct {
	Title string `json:"title"`
	Kind  string `json:"kind"`
	// ValueScale is 'numeric' (a mark out of MaxScore, required) or 'ordinal'
	// (an AD/A/B/C level, MaxScore must be omitted). Omitted means numeric.
	ValueScale   string   `json:"value_scale"`
	MaxScore     *float64 `json:"max_score"`
	DueAt        *string  `json:"due_at"`
	TermID       *string  `json:"term_id"`
	StudentID    *string  `json:"student_id"`
	CriterionIDs []string `json:"criterion_ids"`
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
	if req.Title == "" {
		badRequest(w, "title is required")
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
	case domain.ValueScaleOrdinal:
		if req.MaxScore != nil {
			badRequest(w, "max_score must be omitted for an ordinal assessment")
			return
		}
	default:
		badRequest(w, "value_scale must be numeric or ordinal")
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

	if len(req.CriterionIDs) == 0 {
		badRequest(w, "criterion_ids needs at least one criterio")
		return
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

	var assessmentID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		term, err := repo.ResolveTerm(r.Context(), tx, classID, termIDParam)
		if err != nil {
			return err
		}
		assessmentID, err = repo.CreateAssessment(r.Context(), tx, repo.NewAssessment{
			ClassID:      classID,
			TermID:       term.ID,
			TeacherID:    tc.TeacherID,
			StudentID:    studentID,
			Title:        req.Title,
			Kind:         req.Kind,
			ValueScale:   req.ValueScale,
			MaxScore:     req.MaxScore,
			DueAt:        req.DueAt,
			CriterionIDs: criterionIDs,
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
// same rule deleted criterios follow.
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
		return repo.LogEvent(r.Context(), tx, "assessment.deleted", "assessment",
			&aid, nil, d.StudentID, &d.ClassID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// createScoreRequest carries the value of one piece of work: RawValue for a
// numeric evidence, Level for an ordinal one, neither for a status like
// not_submitted.
type createScoreRequest struct {
	StudentID string   `json:"student_id"`
	Status    string   `json:"status"`
	RawValue  *float64 `json:"raw_value"`
	Level     *string  `json:"level"`
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
		var classID uuid.UUID
		var err error
		scoreID, classID, _, err = repo.CreateScore(r.Context(), tx, assessmentID, studentID, tc.TeacherID, req.Status, req.RawValue, req.Level)
		if err != nil {
			return err
		}
		sid := scoreID
		return repo.LogEvent(r.Context(), tx, "score.recorded", "score", &sid, nil, &studentID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": scoreID})
}

type correctScoreRequest struct {
	RawValue *float64 `json:"raw_value"`
	Level    *string  `json:"level"`
	Status   *string  `json:"status"`
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
		var studentID, classID uuid.UUID
		var err error
		newScoreID, studentID, classID, _, err = repo.CorrectScore(r.Context(), tx, scoreID, tc.TeacherID, req.RawValue, req.Level, req.Status)
		if err != nil {
			return err
		}
		sid := newScoreID
		return repo.LogEvent(r.Context(), tx, "score.corrected", "score", &sid, nil, &studentID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": newScoreID})
}
