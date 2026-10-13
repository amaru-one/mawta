package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent"
	"mawta-server/internal/agent/planning"
	"mawta-server/internal/db"
	"mawta-server/internal/repo"
)

// "✦ Generar con Mawta" (docs/api-planificacion.md, "Generate with Mawta").
// Each route records a generation and queues the job that runs it, in one
// transaction, and answers 202 at once; the app polls GET /generations/{id}.
// The planning agent (internal/agent/planning) does the work; what it
// proposes is saved pending, never accepted on the teacher's behalf.

type generationResponse struct {
	ID     uuid.UUID       `json:"id"`
	Kind   string          `json:"kind"`
	Status string          `json:"status"`
	Result json.RawMessage `json:"result,omitempty"`
	Error  *string         `json:"error,omitempty"`
}

func toGenerationResponse(g repo.AgentGeneration, now time.Time) generationResponse {
	out := generationResponse{ID: g.ID, Kind: g.Kind, Status: g.Status, Error: g.Error}
	if g.Status == repo.GenerationCompleted {
		out.Result = g.Result
	}
	if g.Expired(now) {
		msg := repo.ExpiredGenerationMessage
		out.Status, out.Error = repo.GenerationFailed, &msg
	}
	return out
}

// agentAvailable answers 503 agent_unavailable when no model is configured,
// so the app can offer manual creation only.
func (a *API) agentAvailable(w http.ResponseWriter) bool {
	if a.cfg.AnthropicAPIKey != "" {
		return true
	}
	writeAppError(w, db.NewAppError(http.StatusServiceUnavailable, "agent_unavailable",
		"Mawta no puede generar en este momento. Puedes escribirlo a mano."))
	return false
}

// startGeneration records a generation for the requesting teacher and
// queues its job, or returns the one already running for the same target.
// in.Agent says which agent serves it.
func startGeneration(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, in repo.NewGeneration) (repo.AgentGeneration, error) {
	in.RequestedBy = tc.TeacherID
	return agent.Enqueue(ctx, tx, tc.TenantID, in)
}

func writeGeneration(w http.ResponseWriter, g repo.AgentGeneration) {
	writeJSON(w, http.StatusAccepted, toGenerationResponse(g, time.Now()))
}

type experienceProposalRequest struct {
	TermID        string   `json:"term_id"`
	IdeaText      string   `json:"idea_text"`
	ContextText   string   `json:"context_text"`
	CompetencyIDs []string `json:"competency_ids"`
}

// maxContextRunes caps the teacher's event/context text; it is prompt input.
const maxContextRunes = 300

// POST /classes/{classID}/experience-proposals
//
// A proposal built from the teacher's idea. It is not saved as an
// experience: the app shows it for review and saves it with
// POST /classes/{classID}/experiences.
func (a *API) handleCreateExperienceProposal(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	classID, err := pathUUID(r, "classID")
	if err != nil {
		badRequest(w, "invalid classID")
		return
	}
	var req experienceProposalRequest
	if !decodeBody(w, r, &req) {
		return
	}
	in := planning.ExperienceInput{IdeaText: strings.TrimSpace(req.IdeaText), ContextText: strings.TrimSpace(req.ContextText)}
	if utf8.RuneCountInString(in.ContextText) > maxContextRunes {
		writeAppError(w, db.NewAppError(http.StatusBadRequest, "context_too_long", "el evento o contexto no puede pasar de 300 caracteres"))
		return
	}
	if in.TermID, err = uuid.Parse(req.TermID); err != nil {
		badRequest(w, "invalid term_id")
		return
	}
	if in.IdeaText == "" {
		writeAppError(w, db.NewAppError(http.StatusBadRequest, "missing_idea", "cuéntale a Mawta tu idea en una o dos frases"))
		return
	}
	if in.CompetencyIDs, err = parseUUIDList("competency_ids", req.CompetencyIDs); err != nil {
		badRequest(w, err.Error())
		return
	}
	if !a.agentAvailable(w) {
		return
	}

	var g repo.AgentGeneration
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireClassAccess(r.Context(), tx, tc, classID); err != nil {
			return err
		}
		// The term must be one of the class's year (404 otherwise), and the
		// chosen competencies of its área.
		if _, err := repo.ResolvePlanTerm(r.Context(), tx, classID, in.TermID, time.Now()); err != nil {
			return err
		}
		if err := checkCompetenciesOfClass(r.Context(), tx, classID, in.CompetencyIDs); err != nil {
			return err
		}
		input, _ := json.Marshal(in)
		g, err = startGeneration(r.Context(), tx, tc, repo.NewGeneration{
			Agent:     planning.Name,
			Kind:      planning.KindExperience,
			ClassID:   classID,
			TargetKey: planning.TargetKey(planning.KindExperience, classID, nil, uuid.Nil),
			Input:     input,
		})
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeGeneration(w, g)
}

func checkCompetenciesOfClass(ctx context.Context, tx pgx.Tx, classID uuid.UUID, ids []uuid.UUID) error {
	if len(ids) == 0 {
		return nil
	}
	cur, err := repo.GetCurriculum(ctx, tx, classID)
	if err != nil {
		return err
	}
	ofClass := map[uuid.UUID]bool{}
	for _, c := range cur.Competencies {
		ofClass[c.ID] = true
	}
	for _, id := range ids {
		if !ofClass[id] {
			return db.NewAppError(http.StatusUnprocessableEntity, "competency_not_in_subject", "esa competencia no es del área de esta clase")
		}
	}
	return nil
}

type generateCriteriaRequest struct {
	CompetencyID string `json:"competency_id"`
}

// POST /experiences/{experienceID}/criteria/generate
//
// Pending criteria for the capabilities of one competency that have none.
func (a *API) handleGenerateCriteria(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	experienceID, err := pathUUID(r, "experienceID")
	if err != nil {
		badRequest(w, "invalid experienceID")
		return
	}
	var req generateCriteriaRequest
	if !decodeBody(w, r, &req) {
		return
	}
	competencyID, err := uuid.Parse(req.CompetencyID)
	if err != nil {
		badRequest(w, "invalid competency_id")
		return
	}
	if !a.agentAvailable(w) {
		return
	}
	var g repo.AgentGeneration
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID)
		if err != nil {
			return err
		}
		exp, err := repo.GetExperience(r.Context(), tx, experienceID)
		if err != nil {
			return err
		}
		inExperience := false
		for _, c := range exp.Competencies {
			inExperience = inExperience || c.ID == competencyID
		}
		if !inExperience {
			return db.NewAppError(http.StatusUnprocessableEntity, "competency_not_in_experience",
				"esa competencia no está en esta experiencia")
		}
		input, _ := json.Marshal(planning.CriteriaInput{CompetencyID: competencyID})
		g, err = startGeneration(r.Context(), tx, tc, repo.NewGeneration{
			Agent:        planning.Name,
			Kind:         planning.KindCriteria,
			ClassID:      classID,
			ExperienceID: &experienceID,
			TargetKey:    planning.TargetKey(planning.KindCriteria, classID, &experienceID, competencyID),
			Input:        input,
		})
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeGeneration(w, g)
}

// POST /experiences/{experienceID}/evidences/generate
//
// Pending evidences over the experience's criteria that no evidence observes.
func (a *API) handleGenerateEvidences(w http.ResponseWriter, r *http.Request) {
	a.generateForExperience(w, r, planning.KindEvidences)
}

// POST /experiences/{experienceID}/sessions/generate
//
// Pending session entries on the experience's class dates without one.
func (a *API) handleGenerateSessions(w http.ResponseWriter, r *http.Request) {
	a.generateForExperience(w, r, planning.KindSessions)
}

func (a *API) generateForExperience(w http.ResponseWriter, r *http.Request, kind string) {
	tc := tenantCtxFrom(r)
	experienceID, err := pathUUID(r, "experienceID")
	if err != nil {
		badRequest(w, "invalid experienceID")
		return
	}
	if !a.agentAvailable(w) {
		return
	}
	var g repo.AgentGeneration
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, err := a.requireExperienceAccess(r.Context(), tx, tc, experienceID)
		if err != nil {
			return err
		}
		g, err = startGeneration(r.Context(), tx, tc, repo.NewGeneration{
			Agent:        planning.Name,
			Kind:         kind,
			ClassID:      classID,
			ExperienceID: &experienceID,
			TargetKey:    planning.TargetKey(kind, classID, &experienceID, uuid.Nil),
		})
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeGeneration(w, g)
}

// GET /generations/{generationID}
//
// The state of a generation. A generation past its deadline reads as failed.
// error_detail never leaves the server.
func (a *API) handleGetGeneration(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	generationID, err := pathUUID(r, "generationID")
	if err != nil {
		badRequest(w, "invalid generationID")
		return
	}
	var g repo.AgentGeneration
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		var err error
		if g, err = repo.GetGeneration(r.Context(), tx, generationID); err != nil {
			return err
		}
		return a.requireClassAccess(r.Context(), tx, tc, g.ClassID)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, toGenerationResponse(g, time.Now()))
}
