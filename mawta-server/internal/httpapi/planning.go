package httpapi

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/repo"
)

// Term planning: "Tu trimestre", the curriculum and calendar it is planned
// against, and the learning experiences themselves. The contract is
// docs/api-planificacion.md. Every route reaches a class — directly or
// through an experience, criterion or evidence — and is guarded by
// requireClassAccess on that class.

// GET /classes/{classID}/plan?term_id=
//
// "Tu trimestre". Without term_id, the term that contains today, or else the
// next one.
func (a *API) handleClassPlan(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	termIDParam := queryUUID(r, "term_id")

	var plan repo.Plan
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		today, err := repo.TenantToday(r.Context(), tx, tc.TenantID)
		if err != nil {
			return err
		}
		term, err := repo.ResolvePlanTerm(r.Context(), tx, classID, termIDParam, today)
		if err != nil {
			return err
		}
		plan, err = repo.GetPlan(r.Context(), tx, classID, term)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, plan)
}

// GET /classes/{classID}/curriculum
//
// The competencies of the class's área, each with its capabilities and the
// performances of the class's grade. No standards: criteria never come from
// them.
func (a *API) handleClassCurriculum(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	var out repo.Curriculum
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		var err error
		out, err = repo.GetCurriculum(r.Context(), tx, classID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// GET /classes/{classID}/calendar?from=&to=
//
// Class dates and non-teaching days in a range at most one term long, for
// choosing experience dates and laying out sessions.
func (a *API) handleClassCalendar(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	from, err := time.Parse(dateLayout, r.URL.Query().Get("from"))
	if err != nil {
		badRequest(w, "from must be a YYYY-MM-DD date")
		return
	}
	to, err := time.Parse(dateLayout, r.URL.Query().Get("to"))
	if err != nil {
		badRequest(w, "to must be a YYYY-MM-DD date")
		return
	}

	var out repo.Calendar
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		var err error
		out, err = repo.GetCalendar(r.Context(), tx, classID, from, to)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// GET /experiences/{experienceID}
//
// The whole experience, with the warnings the summary screen shows.
func (a *API) handleGetExperience(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, err := pathUUID(r, "experienceID")
	if err != nil {
		badRequest(w, "invalid experienceID")
		return
	}
	var out repo.Experience
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if _, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID); err != nil {
			return err
		}
		var err error
		out, err = repo.GetExperience(r.Context(), tx, experienceID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// dateLayout is how planning dates travel: YYYY-MM-DD.
const dateLayout = "2006-01-02"

// ---------------------------------------------------------------- writes --
//
// Each write follows handleCreateCriterion: parse the path and body (ids as
// strings, parsed here so a bad one is a 400 naming the field), then in one
// tenant transaction guard the class, write, log the event, and answer with
// the written object as the experience read shows it.

// decodeBody reads a JSON body into v, answering 400 itself on failure.
func decodeBody(w http.ResponseWriter, r *http.Request, v any) bool {
	if err := json.NewDecoder(r.Body).Decode(v); err != nil {
		badRequest(w, "invalid body")
		return false
	}
	return true
}

func parseUUIDList(field string, raw []string) ([]uuid.UUID, error) {
	out := make([]uuid.UUID, 0, len(raw))
	for _, s := range raw {
		id, err := uuid.Parse(s)
		if err != nil {
			return nil, fmt.Errorf("invalid %s", field)
		}
		out = append(out, id)
	}
	return out, nil
}

func parseOptionalUUIDList(field string, raw *[]string) (*[]uuid.UUID, error) {
	if raw == nil {
		return nil, nil
	}
	ids, err := parseUUIDList(field, *raw)
	if err != nil {
		return nil, err
	}
	return &ids, nil
}

func parseOptionalDate(field string, raw *string) (*time.Time, error) {
	if raw == nil {
		return nil, nil
	}
	d, err := time.Parse(dateLayout, *raw)
	if err != nil {
		return nil, fmt.Errorf("%s must be a YYYY-MM-DD date", field)
	}
	return &d, nil
}

// nullableString tells an absent field from an explicit null: set is true
// whenever the key was present, and value is nil for null.
type nullableString struct {
	set   bool
	value *string
}

func (n *nullableString) UnmarshalJSON(b []byte) error {
	n.set = true
	if string(b) == "null" {
		return nil
	}
	var s string
	if err := json.Unmarshal(b, &s); err != nil {
		return err
	}
	n.value = &s
	return nil
}

func logPlanningEvent(r *http.Request, tx pgx.Tx, action, entityType string, entityID uuid.UUID, classID uuid.UUID) error {
	return repo.LogEvent(r.Context(), tx, action, entityType, &entityID, nil, nil, &classID, nil)
}

// ------------------------------------------------------------ experience --

type createExperienceRequest struct {
	TermID        string   `json:"term_id"`
	Title         string   `json:"title"`
	IdeaText      string   `json:"idea_text"`
	SituationText *string  `json:"situation_text"`
	StartsOn      string   `json:"starts_on"`
	EndsOn        string   `json:"ends_on"`
	CompetencyIDs []string `json:"competency_ids"`
}

// POST /classes/{classID}/experiences
//
// The first step of the flow: the experience is saved as a draft and every
// later step writes to it (decision 1 of the contract).
func (a *API) handleCreateExperience(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	var req createExperienceRequest
	if !decodeBody(w, r, &req) {
		return
	}
	in := repo.ExperienceInput{Title: req.Title, IdeaText: req.IdeaText, SituationText: req.SituationText}
	if in.TermID, err = uuid.Parse(req.TermID); err != nil {
		badRequest(w, "invalid term_id")
		return
	}
	if in.StartsOn, err = time.Parse(dateLayout, req.StartsOn); err != nil {
		badRequest(w, "starts_on must be a YYYY-MM-DD date")
		return
	}
	if in.EndsOn, err = time.Parse(dateLayout, req.EndsOn); err != nil {
		badRequest(w, "ends_on must be a YYYY-MM-DD date")
		return
	}
	if in.CompetencyIDs, err = parseUUIDList("competency_ids", req.CompetencyIDs); err != nil {
		badRequest(w, err.Error())
		return
	}

	var out repo.Experience
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		id, err := repo.CreateExperience(r.Context(), tx, classID, in)
		if err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "experience.created", "learning_experience", id, classID); err != nil {
			return err
		}
		out, err = repo.GetExperience(r.Context(), tx, id)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

type updateExperienceRequest struct {
	Title         *string   `json:"title"`
	SituationText *string   `json:"situation_text"`
	StartsOn      *string   `json:"starts_on"`
	EndsOn        *string   `json:"ends_on"`
	CompetencyIDs *[]string `json:"competency_ids"`
}

// PUT /experiences/{experienceID}
func (a *API) handleUpdateExperience(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, err := pathUUID(r, "experienceID")
	if err != nil {
		badRequest(w, "invalid experienceID")
		return
	}
	var req updateExperienceRequest
	if !decodeBody(w, r, &req) {
		return
	}
	p := repo.ExperiencePatch{Title: req.Title, SituationText: req.SituationText}
	if p.StartsOn, err = parseOptionalDate("starts_on", req.StartsOn); err != nil {
		badRequest(w, err.Error())
		return
	}
	if p.EndsOn, err = parseOptionalDate("ends_on", req.EndsOn); err != nil {
		badRequest(w, err.Error())
		return
	}
	if p.CompetencyIDs, err = parseOptionalUUIDList("competency_ids", req.CompetencyIDs); err != nil {
		badRequest(w, err.Error())
		return
	}

	var out repo.Experience
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID)
		if err != nil {
			return err
		}
		if err := repo.UpdateExperience(r.Context(), tx, experienceID, p); err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "experience.updated", "learning_experience", experienceID, classID); err != nil {
			return err
		}
		out, err = repo.GetExperience(r.Context(), tx, experienceID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// POST /experiences/{experienceID}/confirm
//
// "Revisar y guardar". Answers with the experience and its warnings, which
// never block.
func (a *API) handleConfirmExperience(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, err := pathUUID(r, "experienceID")
	if err != nil {
		badRequest(w, "invalid experienceID")
		return
	}
	var out repo.Experience
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID)
		if err != nil {
			return err
		}
		if err := repo.ConfirmExperience(r.Context(), tx, experienceID); err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "experience.confirmed", "learning_experience", experienceID, classID); err != nil {
			return err
		}
		out, err = repo.GetExperience(r.Context(), tx, experienceID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// POST /experiences/{experienceID}/delete
//
// Its criteria, evidences and session outline go with it.
func (a *API) handleDeleteExperience(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, err := pathUUID(r, "experienceID")
	if err != nil {
		badRequest(w, "invalid experienceID")
		return
	}
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID)
		if err != nil {
			return err
		}
		if err := repo.DeleteExperience(r.Context(), tx, experienceID); err != nil {
			return err
		}
		return logPlanningEvent(r, tx, "experience.deleted", "learning_experience", experienceID, classID)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// -------------------------------------------------------------- criteria --

type createPlannedCriterionRequest struct {
	CompetencyID  string   `json:"competency_id"`
	Description   string   `json:"description"`
	CapabilityIDs []string `json:"capability_ids"`
	PerformanceID string   `json:"performance_id"`
}

// POST /experiences/{experienceID}/criteria
//
// A criterion the teacher writes from one of the class grade's performances,
// looking at one or more capabilities of its competency.
func (a *API) handleCreatePlannedCriterion(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, err := pathUUID(r, "experienceID")
	if err != nil {
		badRequest(w, "invalid experienceID")
		return
	}
	var req createPlannedCriterionRequest
	if !decodeBody(w, r, &req) {
		return
	}
	in := repo.CriterionInput{Description: req.Description}
	if in.CompetencyID, err = uuid.Parse(req.CompetencyID); err != nil {
		badRequest(w, "invalid competency_id")
		return
	}
	if in.PerformanceID, err = uuid.Parse(req.PerformanceID); err != nil {
		badRequest(w, "invalid performance_id")
		return
	}
	if in.CapabilityIDs, err = parseUUIDList("capability_ids", req.CapabilityIDs); err != nil {
		badRequest(w, err.Error())
		return
	}

	var out repo.ExperienceCriterion
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID)
		if err != nil {
			return err
		}
		id, err := repo.CreatePlannedCriterion(r.Context(), tx, experienceID, in)
		if err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "criterion.created", "evaluation_criterion", id, classID); err != nil {
			return err
		}
		out, err = repo.GetPlannedCriterion(r.Context(), tx, id)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

type updatePlannedCriterionRequest struct {
	Description   *string   `json:"description"`
	CapabilityIDs *[]string `json:"capability_ids"`
	PerformanceID *string   `json:"performance_id"`
}

// PUT /criteria/{criterionID}
//
// Editing a Mawta proposal also accepts it.
func (a *API) handleUpdatePlannedCriterion(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	criterionID, err := pathUUID(r, "criterionID")
	if err != nil {
		badRequest(w, "invalid criterionID")
		return
	}
	var req updatePlannedCriterionRequest
	if !decodeBody(w, r, &req) {
		return
	}
	p := repo.CriterionPatch{Description: req.Description}
	if p.CapabilityIDs, err = parseOptionalUUIDList("capability_ids", req.CapabilityIDs); err != nil {
		badRequest(w, err.Error())
		return
	}
	if req.PerformanceID != nil {
		id, err := uuid.Parse(*req.PerformanceID)
		if err != nil {
			badRequest(w, "invalid performance_id")
			return
		}
		p.PerformanceID = &id
	}

	var out repo.ExperienceCriterion
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requirePlannedCriterionAccess(r.Context(), tx, tc, criterionID)
		if err != nil {
			return err
		}
		if err := repo.UpdatePlannedCriterion(r.Context(), tx, criterionID, p); err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "criterion.updated", "evaluation_criterion", criterionID, classID); err != nil {
			return err
		}
		out, err = repo.GetPlannedCriterion(r.Context(), tx, criterionID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// POST /criteria/{criterionID}/accept
func (a *API) handleAcceptPlannedCriterion(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	criterionID, err := pathUUID(r, "criterionID")
	if err != nil {
		badRequest(w, "invalid criterionID")
		return
	}
	var out repo.ExperienceCriterion
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requirePlannedCriterionAccess(r.Context(), tx, tc, criterionID)
		if err != nil {
			return err
		}
		if err := repo.AcceptPlannedCriterion(r.Context(), tx, criterionID); err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "criterion.accepted", "evaluation_criterion", criterionID, classID); err != nil {
			return err
		}
		out, err = repo.GetPlannedCriterion(r.Context(), tx, criterionID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// ------------------------------------------------------------- evidences --

type createPlannedEvidenceRequest struct {
	Name         string   `json:"name"`
	Kind         string   `json:"kind"`
	CriterionIDs []string `json:"criterion_ids"`
	SessionDate  *string  `json:"session_date"`
}

// POST /experiences/{experienceID}/evidences
func (a *API) handleCreatePlannedEvidence(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, err := pathUUID(r, "experienceID")
	if err != nil {
		badRequest(w, "invalid experienceID")
		return
	}
	var req createPlannedEvidenceRequest
	if !decodeBody(w, r, &req) {
		return
	}
	in := repo.EvidenceInput{Name: req.Name, Kind: req.Kind}
	if in.CriterionIDs, err = parseUUIDList("criterion_ids", req.CriterionIDs); err != nil {
		badRequest(w, err.Error())
		return
	}
	if in.SessionDate, err = parseOptionalDate("session_date", req.SessionDate); err != nil {
		badRequest(w, err.Error())
		return
	}

	var out repo.ExperienceEvidence
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID)
		if err != nil {
			return err
		}
		id, err := repo.CreatePlannedEvidence(r.Context(), tx, experienceID, in)
		if err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "planned_evidence.created", "planned_evidence", id, classID); err != nil {
			return err
		}
		out, err = repo.GetPlannedEvidence(r.Context(), tx, id)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

type updatePlannedEvidenceRequest struct {
	Name         *string        `json:"name"`
	Kind         *string        `json:"kind"`
	CriterionIDs *[]string      `json:"criterion_ids"`
	SessionDate  nullableString `json:"session_date"`
}

// PUT /evidences/{evidenceID}
//
// "session_date": null takes the evidence out of its session; leaving the
// key out keeps it where it is. Editing a proposal also accepts it.
func (a *API) handleUpdatePlannedEvidence(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	evidenceID, err := pathUUID(r, "evidenceID")
	if err != nil {
		badRequest(w, "invalid evidenceID")
		return
	}
	var req updatePlannedEvidenceRequest
	if !decodeBody(w, r, &req) {
		return
	}
	p := repo.EvidencePatch{Name: req.Name, Kind: req.Kind, SessionDateSet: req.SessionDate.set}
	if p.CriterionIDs, err = parseOptionalUUIDList("criterion_ids", req.CriterionIDs); err != nil {
		badRequest(w, err.Error())
		return
	}
	if p.SessionDate, err = parseOptionalDate("session_date", req.SessionDate.value); err != nil {
		badRequest(w, err.Error())
		return
	}

	var out repo.ExperienceEvidence
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireEvidenceAccess(r.Context(), tx, tc, evidenceID)
		if err != nil {
			return err
		}
		if err := repo.UpdatePlannedEvidence(r.Context(), tx, evidenceID, p); err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "planned_evidence.updated", "planned_evidence", evidenceID, classID); err != nil {
			return err
		}
		out, err = repo.GetPlannedEvidence(r.Context(), tx, evidenceID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// POST /evidences/{evidenceID}/accept
func (a *API) handleAcceptPlannedEvidence(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	evidenceID, err := pathUUID(r, "evidenceID")
	if err != nil {
		badRequest(w, "invalid evidenceID")
		return
	}
	var out repo.ExperienceEvidence
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireEvidenceAccess(r.Context(), tx, tc, evidenceID)
		if err != nil {
			return err
		}
		if err := repo.AcceptPlannedEvidence(r.Context(), tx, evidenceID); err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "planned_evidence.accepted", "planned_evidence", evidenceID, classID); err != nil {
			return err
		}
		out, err = repo.GetPlannedEvidence(r.Context(), tx, evidenceID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// POST /evidences/{evidenceID}/delete
func (a *API) handleDeletePlannedEvidence(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	evidenceID, err := pathUUID(r, "evidenceID")
	if err != nil {
		badRequest(w, "invalid evidenceID")
		return
	}
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireEvidenceAccess(r.Context(), tx, tc, evidenceID)
		if err != nil {
			return err
		}
		if err := repo.DeletePlannedEvidence(r.Context(), tx, evidenceID); err != nil {
			return err
		}
		return logPlanningEvent(r, tx, "planned_evidence.deleted", "planned_evidence", evidenceID, classID)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ------------------------------------------------------- session outline --

type putSessionRequest struct {
	Title             string  `json:"title"`
	Topics            *string `json:"topics"`
	PlannedEvidenceID *string `json:"planned_evidence_id"`
}

// sessionPath parses the experience id and the date of a session route.
func sessionPath(w http.ResponseWriter, r *http.Request) (uuid.UUID, time.Time, bool) {
	experienceID, err := pathUUID(r, "experienceID")
	if err != nil {
		badRequest(w, "invalid experienceID")
		return uuid.Nil, time.Time{}, false
	}
	date, err := time.Parse(dateLayout, chi.URLParam(r, "date"))
	if err != nil {
		badRequest(w, "date must be a YYYY-MM-DD date")
		return uuid.Nil, time.Time{}, false
	}
	return experienceID, date, true
}

// PUT /experiences/{experienceID}/sessions/{date}
//
// Creates or replaces that date's entry, and accepts it.
func (a *API) handlePutSessionEntry(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, date, ok := sessionPath(w, r)
	if !ok {
		return
	}
	var req putSessionRequest
	if !decodeBody(w, r, &req) {
		return
	}
	in := repo.SessionInput{Title: req.Title, Topics: req.Topics}
	if req.PlannedEvidenceID != nil {
		id, err := uuid.Parse(*req.PlannedEvidenceID)
		if err != nil {
			badRequest(w, "invalid planned_evidence_id")
			return
		}
		in.PlannedEvidenceID = &id
	}

	var out repo.ExperienceSession
	err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID)
		if err != nil {
			return err
		}
		if err := repo.PutSessionEntry(r.Context(), tx, experienceID, date, in); err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "session_outline.saved", "learning_experience", experienceID, classID); err != nil {
			return err
		}
		out, err = repo.GetSessionEntry(r.Context(), tx, experienceID, date)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// POST /experiences/{experienceID}/sessions/{date}/accept
func (a *API) handleAcceptSessionEntry(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, date, ok := sessionPath(w, r)
	if !ok {
		return
	}
	var out repo.ExperienceSession
	err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID)
		if err != nil {
			return err
		}
		if err := repo.AcceptSessionEntry(r.Context(), tx, experienceID, date); err != nil {
			return err
		}
		if err := logPlanningEvent(r, tx, "session_outline.accepted", "learning_experience", experienceID, classID); err != nil {
			return err
		}
		out, err = repo.GetSessionEntry(r.Context(), tx, experienceID, date)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// POST /experiences/{experienceID}/sessions/{date}/delete
func (a *API) handleDeleteSessionEntry(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, date, ok := sessionPath(w, r)
	if !ok {
		return
	}
	err := a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID)
		if err != nil {
			return err
		}
		if err := repo.DeleteSessionEntry(r.Context(), tx, experienceID, date); err != nil {
			return err
		}
		return logPlanningEvent(r, tx, "session_outline.deleted", "learning_experience", experienceID, classID)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
