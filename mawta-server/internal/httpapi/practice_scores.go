package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/repo"
)

type createPracticeScoreRequest struct {
	Title    string   `json:"title"`
	Kind     string   `json:"kind"`
	RawValue *float64 `json:"raw_value"`
	MaxValue *float64 `json:"max_value"`
	Note     *string  `json:"note"`
	TermID   *string  `json:"term_id"`
}

func (a *API) handleCreatePracticeScore(w http.ResponseWriter, r *http.Request) {
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
	var req createPracticeScoreRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid JSON body")
		return
	}
	if req.Title == "" || req.RawValue == nil || req.MaxValue == nil || *req.MaxValue <= 0 {
		badRequest(w, "title, raw_value and a positive max_value are required")
		return
	}
	if req.Kind == "" {
		req.Kind = "otro"
	}

	var termIDParam uuid.UUID
	if req.TermID != nil {
		termIDParam, _ = uuid.Parse(*req.TermID)
	}

	var practiceScoreID uuid.UUID
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
		practiceScoreID, err = repo.CreatePracticeScore(r.Context(), tx, classID, studentID, term.ID, tc.TeacherID,
			req.Title, req.Kind, *req.RawValue, *req.MaxValue, req.Note)
		if err != nil {
			return err
		}
		psid := practiceScoreID
		return repo.LogEvent(r.Context(), tx, "practice_score.created", "practice_score", &psid, nil, &studentID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": practiceScoreID})
}

func (a *API) handleDeletePracticeScore(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	practiceScoreID, err := pathUUID(r, "practiceScoreID")
	if err != nil {
		badRequest(w, "invalid practiceScoreID")
		return
	}

	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requirePracticeScoreAccess(r.Context(), tx, tc, practiceScoreID); err != nil {
			return err
		}
		studentID, classID, err := repo.DeletePracticeScore(r.Context(), tx, practiceScoreID)
		if err != nil {
			return err
		}
		psid := practiceScoreID
		return repo.LogEvent(r.Context(), tx, "practice_score.deleted", "practice_score", &psid, nil, &studentID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "deleted"})
}
