package httpapi

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/domain"
	"mawta-server/internal/repo"
)

// GET /classes/{classID}/students/{studentID}/competencies?term_id=
//
// The registration screen for niveles de logro: every competency of the área,
// the level the teacher has asserted (if any), and whether a conclusión
// descriptiva is mandatory. There is deliberately no suggested level: under
// RVM 094-2020 the level is the teacher's judgement of evidence against the
// criterios, not a number the system arrives at first.
func (a *API) handleStudentCompetencies(w http.ResponseWriter, r *http.Request) {
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

	var rows []repo.CompetencyLevelRow
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
		rows, err = repo.ListClassCompetencyLevels(r.Context(), tx, classID, studentID, term.ID)
		if err != nil {
			return err
		}
		return repo.LogStudentReads(r.Context(), tx, []uuid.UUID{studentID}, tc.TeacherID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"competencies": rows})
}

type assertLevelRequest struct {
	CompetencyID string  `json:"competency_id"`
	Level        string  `json:"level"`
	Note         *string `json:"note"`
	TermID       *string `json:"term_id"`
}

// POST /classes/{classID}/students/{studentID}/competency-levels
//
// Records the teacher's nivel de logro. This is the only writer of the
// official record, and nothing is derived into it: under RVM 094-2020 the
// level is the teacher's judgement of the period's evidence against the
// criterios de evaluación.
func (a *API) handleAssertCompetencyLevel(w http.ResponseWriter, r *http.Request) {
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

	var req assertLevelRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid body")
		return
	}
	competencyID, err := uuid.Parse(req.CompetencyID)
	if err != nil {
		badRequest(w, "invalid competency_id")
		return
	}
	level := strings.ToUpper(strings.TrimSpace(req.Level))
	switch level {
	case domain.LevelAD, domain.LevelA, domain.LevelB, domain.LevelC:
	default:
		badRequest(w, "level must be AD, A, B or C")
		return
	}

	var termIDParam uuid.UUID
	if req.TermID != nil {
		termIDParam, _ = uuid.Parse(*req.TermID)
	}

	var levelID uuid.UUID
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
		levelID, err = repo.AssertCompetencyLevel(r.Context(), tx,
			classID, studentID, competencyID, term.ID, tc.TeacherID, level, req.Note)
		if err != nil {
			return err
		}
		payload, _ := json.Marshal(map[string]any{"level": level, "competency_id": competencyID})
		return repo.LogEvent(r.Context(), tx, "competency_level.asserted", "competency_term_level",
			&levelID, payload, &studentID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": levelID, "level": level})
}

type conclusionRequest struct {
	CompetencyID string  `json:"competency_id"`
	Body         string  `json:"body"`
	Status       string  `json:"status"`
	TermID       *string `json:"term_id"`
	// GenerationID is the Mawta proposal the teacher started from, if any.
	GenerationID *string `json:"generation_id"`
}

// POST /classes/{classID}/students/{studentID}/conclusions
//
// Writes a conclusión descriptiva. Why it is mandatory (or not) is decided
// server-side from the student's live level — the client does not get to
// declare that a conclusion was optional.
func (a *API) handleUpsertConclusion(w http.ResponseWriter, r *http.Request) {
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

	var req conclusionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid body")
		return
	}
	competencyID, err := uuid.Parse(req.CompetencyID)
	if err != nil {
		badRequest(w, "invalid competency_id")
		return
	}
	if strings.TrimSpace(req.Body) == "" {
		badRequest(w, "body is required")
		return
	}
	status := req.Status
	if status == "" {
		status = domain.ConclusionDraft
	}
	if status != domain.ConclusionDraft && status != domain.ConclusionFinal {
		badRequest(w, "status must be draft or final")
		return
	}

	var termIDParam uuid.UUID
	if req.TermID != nil {
		termIDParam, _ = uuid.Parse(*req.TermID)
	}
	var generationID *uuid.UUID
	if req.GenerationID != nil && *req.GenerationID != "" {
		g, err := uuid.Parse(*req.GenerationID)
		if err != nil {
			badRequest(w, "invalid generation_id")
			return
		}
		generationID = &g
	}

	var id uuid.UUID
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
		id, err = repo.UpsertConclusion(r.Context(), tx, classID, studentID, competencyID,
			term.ID, tc.TeacherID, strings.TrimSpace(req.Body), status, generationID)
		if err != nil {
			return err
		}
		payload, _ := json.Marshal(map[string]any{"status": status, "competency_id": competencyID, "generation_id": generationID})
		return repo.LogEvent(r.Context(), tx, "conclusion.written", "descriptive_conclusion",
			&id, payload, &studentID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": id, "status": status})
}
