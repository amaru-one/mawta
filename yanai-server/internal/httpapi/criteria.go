package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/repo"
)

// GET /classes/{classID}/criteria
//
// Every competencia of the class's área with the criterios de evaluación the
// teacher has written for it. Not scoped to a student and no longer accepting
// student_id: nothing here is per-student, because a criterio is what a piece
// of evidencia is tagged with rather than something a student is graded on.
//
// A competencia with no criterios comes back with an empty list rather than
// being omitted: under RVM 094-2020 the criterios are what evidence is read
// against, so a competencia without any is the thing the teacher most needs
// to see.
func (a *API) handleClassCriteria(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	var rows []repo.CompetencyCriteriaRow
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		var err error
		rows, err = repo.ListClassCriteria(r.Context(), tx, classID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"competencies": rows})
}

type createCriterionRequest struct {
	CapabilityID string  `json:"capability_id"`
	Description  string  `json:"description"`
	Code         *string `json:"code"`
}

// POST /classes/{classID}/competencies/{competencyID}/criteria
//
// The teacher writes a criterio for one competencia, anchored to one of its
// capacidades. This is the "criterios are presented by the teacher" path:
// the text is theirs.
func (a *API) handleCreateCriterion(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	competencyID, err := pathUUID(r, "competencyID")
	if err != nil {
		badRequest(w, "invalid competencyID")
		return
	}

	var req createCriterionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid body")
		return
	}
	capabilityID, err := uuid.Parse(req.CapabilityID)
	if err != nil {
		badRequest(w, "invalid capability_id")
		return
	}

	var criterionID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		criterionID, err = repo.CreateCriterion(r.Context(), tx, classID, competencyID, capabilityID,
			req.Code, req.Description)
		if err != nil {
			return err
		}
		payload, _ := json.Marshal(map[string]any{"competency_id": competencyID})
		return repo.LogEvent(r.Context(), tx, "criterion.created", "evaluation_criterion",
			&criterionID, payload, nil, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": criterionID})
}

// GET /competencies/{competencyID}/capabilities
//
// The capacidades a teacher picks from when writing a criterio: a criterio
// must anchor to one, per evaluation_criteria.capability_id.
func (a *API) handleCompetencyCapabilities(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	competencyID, err := pathUUID(r, "competencyID")
	if err != nil {
		badRequest(w, "invalid competencyID")
		return
	}
	var rows []repo.CapabilityRow
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireCompetencyAccess(r.Context(), tx, tc, competencyID); err != nil {
			return err
		}
		var err error
		rows, err = repo.ListCompetencyCapabilities(r.Context(), tx, competencyID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"capabilities": rows})
}

type createCapabilityRequest struct {
	Code string `json:"code"`
	Name string `json:"name"`
}

// POST /competencies/{competencyID}/capabilities
func (a *API) handleCreateCapability(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	competencyID, err := pathUUID(r, "competencyID")
	if err != nil {
		badRequest(w, "invalid competencyID")
		return
	}
	var req createCapabilityRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid body")
		return
	}

	var capabilityID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireCompetencyAccess(r.Context(), tx, tc, competencyID); err != nil {
			return err
		}
		capabilityID, err = repo.CreateCapability(r.Context(), tx, competencyID, req.Code, req.Name)
		if err != nil {
			return err
		}
		return repo.LogEvent(r.Context(), tx, "capability.created", "capability",
			&capabilityID, nil, nil, nil, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": capabilityID})
}

// POST /criteria/{criterionID}/delete
func (a *API) handleDeleteCriterion(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	criterionID, err := pathUUID(r, "criterionID")
	if err != nil {
		badRequest(w, "invalid criterionID")
		return
	}

	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireCriterionAccess(r.Context(), tx, tc, criterionID); err != nil {
			return err
		}
		if err := repo.DeleteCriterion(r.Context(), tx, criterionID); err != nil {
			return err
		}
		return repo.LogEvent(r.Context(), tx, "criterion.deleted", "evaluation_criterion",
			&criterionID, nil, nil, nil, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
