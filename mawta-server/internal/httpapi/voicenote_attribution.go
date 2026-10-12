package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/agent/redaction"
	"mawta-server/internal/db"
	"mawta-server/internal/repo"
)

// A voice note the name sweep discarded (it named only classmates, never its
// student) stays out of the descriptive conclusions without asking anyone.
// The teacher only sees it when it matters — when discarding it leaves too
// little evidence to propose a conclusion — and then decides: the note was
// recorded on the wrong student (reassign) or it does belong here (confirm).

type reassignVoiceNoteRequest struct {
	StudentID string `json:"student_id"`
}

type attributionResponse struct {
	ID                uuid.UUID `json:"id"`
	StudentID         uuid.UUID `json:"student_id"`
	AttributionStatus string    `json:"attribution_status"`
}

// POST /voice-notes/{voiceNoteID}/reassign
//
// Moves the note to another student of the same class and sweeps it again
// around that student. Until the new sweep finishes the note is pending.
func (a *API) handleVoiceNoteReassign(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	voiceNoteID, err := pathUUID(r, "voiceNoteID")
	if err != nil {
		badRequest(w, "invalid voiceNoteID")
		return
	}
	var req reassignVoiceNoteRequest
	if !decodeBody(w, r, &req) {
		return
	}
	studentID, err := uuid.Parse(req.StudentID)
	if err != nil {
		badRequest(w, "invalid student_id")
		return
	}

	var out attributionResponse
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireVoiceNoteAccess(r.Context(), tx, tc, voiceNoteID); err != nil {
			return err
		}
		note, err := repo.GetVoiceNoteForRedaction(r.Context(), tx, voiceNoteID)
		if err != nil {
			return err
		}
		if err := a.requireStudentOnRoster(r.Context(), tx, tc, note.ClassID, studentID); err != nil {
			return err
		}
		if note.StudentID == studentID {
			return db.NewAppError(http.StatusUnprocessableEntity, "same_student",
				"La nota ya está guardada en este estudiante. Usa «Sí es de este estudiante».")
		}
		if err := repo.ReassignVoiceNote(r.Context(), tx, voiceNoteID, studentID); err != nil {
			return err
		}
		payload, _ := json.Marshal(map[string]string{"from_student_id": note.StudentID.String()})
		vid, classID := voiceNoteID, note.ClassID
		if err := repo.LogEvent(r.Context(), tx, "voice_note.reassigned", "voice_note", &vid, payload, &studentID, &classID, nil); err != nil {
			return err
		}
		out = attributionResponse{ID: voiceNoteID, StudentID: studentID, AttributionStatus: repo.AttributionPending}
		if a.cfg.AnthropicAPIKey == "" {
			return nil // stays pending until the agents can run
		}
		note.StudentID = studentID
		return redaction.Queue(r.Context(), tx, tc.TenantID, note, tc.TeacherID, true)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// POST /voice-notes/{voiceNoteID}/confirm
//
// The teacher says a discarded note does belong to its student. Only a note
// discarded for naming other students can be confirmed: an unreadable one has
// nothing to use.
func (a *API) handleVoiceNoteConfirm(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	voiceNoteID, err := pathUUID(r, "voiceNoteID")
	if err != nil {
		badRequest(w, "invalid voiceNoteID")
		return
	}

	var out attributionResponse
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := a.requireVoiceNoteAccess(r.Context(), tx, tc, voiceNoteID); err != nil {
			return err
		}
		note, err := repo.GetVoiceNoteForRedaction(r.Context(), tx, voiceNoteID)
		if err != nil {
			return err
		}
		if err := repo.ConfirmVoiceNote(r.Context(), tx, voiceNoteID); err != nil {
			return err
		}
		vid, sid, classID := voiceNoteID, note.StudentID, note.ClassID
		if err := repo.LogEvent(r.Context(), tx, "voice_note.confirmed", "voice_note", &vid, nil, &sid, &classID, nil); err != nil {
			return err
		}
		out = attributionResponse{ID: voiceNoteID, StudentID: note.StudentID, AttributionStatus: repo.AttributionConfirmed}
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}
