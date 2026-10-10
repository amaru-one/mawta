package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent/conclusions"
	"mawta-server/internal/agent/redaction"
	"mawta-server/internal/db"
	"mawta-server/internal/repo"
)

// "✦ Generar con Mawta" for a conclusión descriptiva (docs/api-conclusiones.md).
// The request is checked synchronously — a level must be asserted and there
// must be enough graded evidence — so the teacher learns at once why Mawta
// cannot help; otherwise a generation is queued and polled through
// GET /generations/{id}, like the planning agent's.

type conclusionGenerateRequest struct {
	CompetencyID string  `json:"competency_id"`
	TermID       *string `json:"term_id"`
}

// insufficientEvidence is the 422 body when the material is too thin. When
// the sweep discarded every voice note of the student (the worst case), the
// discarded notes come along so the teacher can move them to the right
// student or confirm they belong here.
type insufficientEvidence struct {
	Error    errorBody                 `json:"error"`
	Evidence insufficientEvidenceStats `json:"evidence"`
}

type insufficientEvidenceStats struct {
	GradedCount         int                       `json:"graded_count"`
	Minimum             int                       `json:"minimum"`
	UsableVoiceNotes    int                       `json:"usable_voice_notes"`
	DiscardedVoiceNotes []repo.DiscardedVoiceNote `json:"discarded_voice_notes"`
}

// POST /classes/{classID}/students/{studentID}/conclusions/generate
func (a *API) handleGenerateConclusion(w http.ResponseWriter, r *http.Request) {
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
	var req conclusionGenerateRequest
	if !decodeBody(w, r, &req) {
		return
	}
	competencyID, err := uuid.Parse(req.CompetencyID)
	if err != nil {
		badRequest(w, "invalid competency_id")
		return
	}
	var termIDParam uuid.UUID
	if req.TermID != nil && *req.TermID != "" {
		if termIDParam, err = uuid.Parse(*req.TermID); err != nil {
			badRequest(w, "invalid term_id")
			return
		}
	}
	if !a.agentAvailable(w) {
		return
	}

	var g repo.AgentGeneration
	var thin *insufficientEvidence
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		scope, err := a.conclusionScope(r.Context(), tx, tc, classID, studentID, competencyID, termIDParam)
		if err != nil {
			return err
		}
		// Notes recorded before the sweep existed, or while no model was
		// configured, are swept now. The proposal may start before they
		// finish; it then says how many notes were still in process.
		if err := a.queuePendingSweeps(r.Context(), tx, tc, scope); err != nil {
			return err
		}

		m, err := conclusions.Gather(r.Context(), tx, scope)
		if err != nil {
			return err
		}
		if err := m.Check(); err != nil {
			if !errors.Is(err, conclusions.ErrInsufficientEvidence) {
				return err
			}
			// Not an error for the transaction: the sweeps queued above
			// must still commit.
			thin = &insufficientEvidence{
				Error: errorBody{Code: conclusions.ErrInsufficientEvidence.Code, Message: conclusions.ErrInsufficientEvidence.Message},
				Evidence: insufficientEvidenceStats{
					GradedCount: m.Graded, Minimum: conclusions.MinGradedEvidences,
					UsableVoiceNotes: len(m.VoiceNotes), DiscardedVoiceNotes: []repo.DiscardedVoiceNote{},
				},
			}
			if m.OnlyDiscardedNotes() {
				if thin.Evidence.DiscardedVoiceNotes, err = repo.ListDiscardedVoiceNotes(r.Context(), tx, classID, studentID, scope.TermID); err != nil {
					return err
				}
				return repo.LogStudentReads(r.Context(), tx, []uuid.UUID{studentID}, tc.TeacherID, &classID, nil)
			}
			return nil
		}

		input, _ := json.Marshal(map[string]string{"competency_id": competencyID.String(), "term_id": scope.TermID.String()})
		sid, cid, tid := scope.StudentID, scope.CompetencyID, scope.TermID
		g, err = startGeneration(r.Context(), tx, tc, repo.NewGeneration{
			Agent:        conclusions.Name,
			Kind:         conclusions.KindConclusion,
			ClassID:      classID,
			StudentID:    &sid,
			CompetencyID: &cid,
			TermID:       &tid,
			TargetKey:    conclusions.TargetKey(scope),
			Input:        input,
		})
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}
	if thin != nil {
		writeJSON(w, http.StatusUnprocessableEntity, thin)
		return
	}
	writeGeneration(w, g)
}

// GET /classes/{classID}/students/{studentID}/conclusions/generation?competency_id=&term_id=
//
// The latest conclusion generation for that competency and term, so a
// proposal survives a reload. {"generation": null} when there is none.
func (a *API) handleLatestConclusionGeneration(w http.ResponseWriter, r *http.Request) {
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
	competencyID := queryUUID(r, "competency_id")
	if competencyID == uuid.Nil {
		badRequest(w, "invalid competency_id")
		return
	}
	termIDParam := queryUUID(r, "term_id")

	var out *generationResponse
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		scope, err := a.conclusionScope(r.Context(), tx, tc, classID, studentID, competencyID, termIDParam)
		if err != nil {
			return err
		}
		g, ok, err := repo.LatestConclusionGeneration(r.Context(), tx, scope.StudentID, scope.CompetencyID, scope.TermID)
		if err != nil || !ok {
			return err
		}
		resp := toGenerationResponse(g, time.Now())
		out = &resp
		return repo.LogStudentReads(r.Context(), tx, []uuid.UUID{studentID}, tc.TeacherID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"generation": out})
}

// GET /classes/{classID}/students/{studentID}/voice-notes/discarded?term_id=
//
// The notes the sweep discarded for this student in the term, only when they
// are all the student has: that is the one case the teacher is asked to look
// at them (move or confirm). Otherwise {"voice_notes": []}.
func (a *API) handleDiscardedVoiceNotes(w http.ResponseWriter, r *http.Request) {
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

	notes := []repo.DiscardedVoiceNote{}
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
		usable, counts, err := repo.ListConclusionVoiceNotes(r.Context(), tx, classID, studentID, term.ID)
		if err != nil {
			return err
		}
		if len(usable) > 0 || counts.Discarded == 0 {
			return nil
		}
		if notes, err = repo.ListDiscardedVoiceNotes(r.Context(), tx, classID, studentID, term.ID); err != nil {
			return err
		}
		return repo.LogStudentReads(r.Context(), tx, []uuid.UUID{studentID}, tc.TeacherID, &classID, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"voice_notes": notes})
}

// conclusionScope authorizes a conclusion request and resolves its term: the
// teacher teaches the class, the student is on its roster, and the
// competency is one of the class's área.
func (a *API) conclusionScope(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, classID, studentID, competencyID, termID uuid.UUID) (conclusions.Scope, error) {
	if err := a.requireClassAccess(ctx, tx, tc, classID); err != nil {
		return conclusions.Scope{}, err
	}
	if err := a.requireStudentOnRoster(ctx, tx, tc, classID, studentID); err != nil {
		return conclusions.Scope{}, err
	}
	ok, err := repo.CompetencyInClass(ctx, tx, classID, competencyID)
	if err != nil {
		return conclusions.Scope{}, err
	}
	if !ok {
		return conclusions.Scope{}, db.NewAppError(http.StatusNotFound, "not_found", "esa competencia no es de esta clase")
	}
	term, err := repo.ResolveTerm(ctx, tx, classID, termID)
	if err != nil {
		return conclusions.Scope{}, err
	}
	return conclusions.Scope{ClassID: classID, StudentID: studentID, CompetencyID: competencyID, TermID: term.ID}, nil
}

// queuePendingSweeps queues the name sweep of the student's transcribed notes
// in the term that were never swept.
func (a *API) queuePendingSweeps(ctx context.Context, tx pgx.Tx, tc db.TenantCtx, s conclusions.Scope) error {
	ids, err := repo.PendingVoiceNotesForStudentTerm(ctx, tx, s.ClassID, s.StudentID, s.TermID)
	if err != nil {
		return err
	}
	for _, id := range ids {
		note, err := repo.GetVoiceNoteForRedaction(ctx, tx, id)
		if err != nil {
			return err
		}
		if err := redaction.Queue(ctx, tx, tc.TenantID, note, note.TeacherID, false); err != nil {
			return err
		}
	}
	return nil
}
