package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"yanai-server/internal/db"
	"yanai-server/internal/domain"
	"yanai-server/internal/repo"
)

func (a *API) handleSessionRoster(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	sessionID, err := pathUUID(r, "sessionID")
	if err != nil {
		badRequest(w, "invalid sessionID")
		return
	}
	q := r.URL.Query().Get("q")

	var resp repo.SessionRoster
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		header, err := repo.GetSessionHeader(r.Context(), tx, sessionID)
		if err != nil {
			return err
		}
		sd, err := parseSessionDate(header.SessionDate)
		if err != nil {
			return err
		}
		roster, studentIDs, err := repo.GetSessionRoster(r.Context(), tx, sessionID, header.ClassID, sd, header.TermID, q)
		if err != nil {
			return err
		}
		if err := repo.LogStudentReads(r.Context(), tx, studentIDs, tc.TeacherID, &header.ClassID, &sessionID); err != nil {
			return err
		}
		resp = repo.SessionRoster{Header: header, Roster: roster}
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

type attendanceRequest struct {
	Status      string  `json:"status"`
	MinutesLate *int16  `json:"minutes_late"`
	Note        *string `json:"note"`
}

func (a *API) handleAttendanceUpsert(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	sessionID, err := pathUUID(r, "sessionID")
	if err != nil {
		badRequest(w, "invalid sessionID")
		return
	}
	studentID, err := pathUUID(r, "studentID")
	if err != nil {
		badRequest(w, "invalid studentID")
		return
	}
	var req attendanceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid JSON body")
		return
	}

	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := repo.UpsertAttendance(r.Context(), tx, sessionID, studentID, tc.TeacherID, req.Status, req.MinutesLate, req.Note); err != nil {
			return err
		}
		if err := repo.MaybeStampAttendanceTaken(r.Context(), tx, sessionID, tc.TeacherID); err != nil {
			return err
		}
		payload, _ := json.Marshal(map[string]any{"status": req.Status})
		classID, _, err := repo.GetSessionMeta(r.Context(), tx, sessionID)
		if err != nil {
			return err
		}
		if err := repo.LogEvent(r.Context(), tx, "attendance.marked", "attendance_record", nil, payload, &studentID, &classID, &sessionID); err != nil {
			return err
		}
		if req.Status == domain.AttendanceAbsent {
			jobPayload, _ := json.Marshal(map[string]any{"class_id": classID, "student_id": studentID})
			uniqueKey := "risk.detect:" + studentID.String() + ":" + classID.String()
			if err := repo.EnqueueJob(r.Context(), tx, tc.TenantID, domain.JobKindRiskDetect, 2, jobPayload, uniqueKey); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": req.Status})
}

func (a *API) handleMarkAllPresent(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	sessionID, err := pathUUID(r, "sessionID")
	if err != nil {
		badRequest(w, "invalid sessionID")
		return
	}

	var marked int
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, sessionDate, err := repo.GetSessionMeta(r.Context(), tx, sessionID)
		if err != nil {
			return err
		}
		marked, err = repo.MarkAllPresent(r.Context(), tx, sessionID, classID, tc.TeacherID, sessionDate)
		if err != nil {
			return err
		}
		if err := repo.MaybeStampAttendanceTaken(r.Context(), tx, sessionID, tc.TeacherID); err != nil {
			return err
		}
		if err := repo.LogEvent(r.Context(), tx, "attendance.marked_bulk", "class_session", &sessionID, nil, nil, &classID, &sessionID); err != nil {
			return err
		}
		jobPayload, _ := json.Marshal(map[string]any{"class_id": classID})
		uniqueKey := "risk.detect:" + classID.String()
		return repo.EnqueueJob(r.Context(), tx, tc.TenantID, domain.JobKindRiskDetect, 3, jobPayload, uniqueKey)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"marked": marked})
}

type observationRequest struct {
	ParticipationLevel *int16      `json:"participation_level"`
	Note               *string     `json:"note"`
	FlagTypeIDs        []uuid.UUID `json:"flag_type_ids"`
}

func (a *API) handleObservationUpsert(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	sessionID, err := pathUUID(r, "sessionID")
	if err != nil {
		badRequest(w, "invalid sessionID")
		return
	}
	studentID, err := pathUUID(r, "studentID")
	if err != nil {
		badRequest(w, "invalid studentID")
		return
	}
	var req observationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid JSON body")
		return
	}

	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := repo.UpsertObservation(r.Context(), tx, sessionID, studentID, tc.TeacherID, req.ParticipationLevel, req.Note, req.FlagTypeIDs); err != nil {
			return err
		}
		classID, _, err := repo.GetSessionMeta(r.Context(), tx, sessionID)
		if err != nil {
			return err
		}
		return repo.LogEvent(r.Context(), tx, "observation.recorded", "session_observation", nil, nil, &studentID, &classID, &sessionID)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (a *API) handleCreateVoiceNote(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	sessionID, err := pathUUID(r, "sessionID")
	if err != nil {
		badRequest(w, "invalid sessionID")
		return
	}
	studentID, err := pathUUID(r, "studentID")
	if err != nil {
		badRequest(w, "invalid studentID")
		return
	}

	const maxAudioBytes = 2 << 20 // 1 min at ~128 kbps is ~1 MB; 2x headroom
	const minAudioBytes = 1000    // rejects near-empty/mis-tap blobs
	const maxDurationMs = 60_000  // voice notes are capped at 1 minute

	var durationMs int32
	var mimeType *string
	var byteSize *int64
	var audioBytes []byte

	contentType := r.Header.Get("Content-Type")
	if len(contentType) >= 19 && contentType[:19] == "multipart/form-data" {
		if err := r.ParseMultipartForm(maxAudioBytes); err != nil {
			badRequest(w, "invalid multipart form")
			return
		}
		if v := r.FormValue("duration_ms"); v != "" {
			n, err := strconv.Atoi(v)
			if err != nil {
				badRequest(w, "invalid duration_ms")
				return
			}
			durationMs = int32(n)
		}
		if v := r.FormValue("mime_type"); v != "" {
			mimeType = &v
		}
		if file, header, err := r.FormFile("audio"); err == nil {
			defer file.Close()
			audioBytes, err = io.ReadAll(io.LimitReader(file, maxAudioBytes+1))
			if err != nil {
				writeError(w, err)
				return
			}
			if len(audioBytes) > maxAudioBytes {
				unprocessable(w, "audio exceeds the 1-minute size limit")
				return
			}
			byteSize = new(int64)
			*byteSize = int64(len(audioBytes))
			if mimeType == nil {
				ct := header.Header.Get("Content-Type")
				mimeType = &ct
			}
		}
	} else {
		var body struct {
			DurationMs int32   `json:"duration_ms"`
			MimeType   *string `json:"mime_type"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			badRequest(w, "invalid JSON body")
			return
		}
		durationMs = body.DurationMs
		mimeType = body.MimeType
	}

	if durationMs > maxDurationMs {
		unprocessable(w, "voice notes cannot be longer than 1 minute")
		return
	}
	if len(audioBytes) < minAudioBytes {
		unprocessable(w, "audio is missing or too short to be a valid recording")
		return
	}

	var voiceNoteID uuid.UUID
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		classID, _, err := repo.GetSessionMeta(r.Context(), tx, sessionID)
		if err != nil {
			return err
		}
		voiceNoteID, err = repo.CreateVoiceNote(r.Context(), tx, sessionID, studentID, classID, tc.TeacherID, durationMs, audioBytes, mimeType, byteSize)
		if err != nil {
			return err
		}
		vid := voiceNoteID
		return repo.LogEvent(r.Context(), tx, "voice_note.recorded", "voice_note", &vid, nil, &studentID, &classID, &sessionID)
	})
	if err != nil {
		writeError(w, err)
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{"id": voiceNoteID})
}

func (a *API) handleVoiceNoteAudio(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	voiceNoteID, err := pathUUID(r, "voiceNoteID")
	if err != nil {
		badRequest(w, "invalid voiceNoteID")
		return
	}

	var file repo.VoiceNoteFile
	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		var err error
		file, err = repo.GetVoiceNoteFile(r.Context(), tx, voiceNoteID)
		return err
	})
	if err != nil {
		writeError(w, err)
		return
	}

	if file.MimeType != nil {
		w.Header().Set("Content-Type", *file.MimeType)
	}

	if file.Audio != nil {
		w.Header().Set("Content-Length", strconv.Itoa(len(file.Audio)))
		_, _ = w.Write(file.Audio)
		return
	}

	// Legacy fallback: pre-migration recordings still on disk.
	if file.StorageKey == nil {
		writeAppError(w, db.NewAppError(http.StatusNotFound, "not_found", "audio not found"))
		return
	}
	fullPath := filepath.Join(a.cfg.StorageDir, *file.StorageKey)
	f, err := os.Open(fullPath)
	if err != nil {
		writeAppError(w, db.NewAppError(http.StatusNotFound, "not_found", "audio file not found"))
		return
	}
	defer f.Close()
	_, _ = io.Copy(w, f)
}

type transcriptRequest struct {
	Transcript string  `json:"transcript"`
	Language   *string `json:"language"`
}

func (a *API) handleVoiceNoteTranscript(w http.ResponseWriter, r *http.Request) {
	tc := tenantCtxFrom(r)
	voiceNoteID, err := pathUUID(r, "voiceNoteID")
	if err != nil {
		badRequest(w, "invalid voiceNoteID")
		return
	}
	var req transcriptRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid JSON body")
		return
	}

	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := repo.SetVoiceNoteTranscript(r.Context(), tx, voiceNoteID, req.Transcript, req.Language); err != nil {
			return err
		}
		vid := voiceNoteID
		return repo.LogEvent(r.Context(), tx, "voice_note.transcribed", "voice_note", &vid, nil, nil, nil, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

func (a *API) handleVoiceNoteSave(w http.ResponseWriter, r *http.Request) {
	a.setVoiceNoteStatus(w, r, domain.VoiceNoteSaved, "voice_note.saved")
}

func (a *API) handleVoiceNoteDiscard(w http.ResponseWriter, r *http.Request) {
	a.setVoiceNoteStatus(w, r, domain.VoiceNoteDiscarded, "voice_note.discarded")
}

func (a *API) setVoiceNoteStatus(w http.ResponseWriter, r *http.Request, status, action string) {
	tc := tenantCtxFrom(r)
	voiceNoteID, err := pathUUID(r, "voiceNoteID")
	if err != nil {
		badRequest(w, "invalid voiceNoteID")
		return
	}

	err = a.db.WithTenantTx(r.Context(), tc, func(tx pgx.Tx) error {
		if err := repo.SetVoiceNoteStatus(r.Context(), tx, voiceNoteID, status); err != nil {
			return err
		}
		vid := voiceNoteID
		return repo.LogEvent(r.Context(), tx, action, "voice_note", &vid, nil, nil, nil, nil)
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": status})
}

func parseSessionDate(s string) (time.Time, error) {
	return time.Parse("2006-01-02", s)
}
