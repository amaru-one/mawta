package handlers

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/repo"
	"mawta-server/internal/stt"
)

// Transcriber defines the interface for the STT service used by the handler.
// This allows for testing with mocks while keeping the concrete implementation
// in internal/stt without an abstraction layer.
type Transcriber interface {
	Transcribe(ctx context.Context, audioMP3 []byte) (string, error)
}

type transcribePayload struct {
	VoiceNoteID uuid.UUID `json:"voice_note_id"`
}

// VoiceNoteTranscribe returns a handler bound to one Transcriber, built once
// when the registry is assembled rather than per job — this is the first job
// kind that needs an external dependency;
func VoiceNoteTranscribe(transcriber Transcriber) func(ctx context.Context, tx pgx.Tx, jobID int64, payload []byte) error {
	return func(ctx context.Context, tx pgx.Tx, jobID int64, payload []byte) error {
		var p transcribePayload
		if err := json.Unmarshal(payload, &p); err != nil {
			return err
		}

		file, err := repo.GetVoiceNoteFile(ctx, tx, p.VoiceNoteID)
		if errors.Is(err, pgx.ErrNoRows) {
			// Discarded (soft-deleted) before the job ran. Nothing to do.
			return nil
		}
		if err != nil {
			return err
		}
		if file.Audio == nil {
			// Legacy note: audio only ever reached storage_key on disk, from
			// before audio moved into this table. Not worth reading
			// STORAGE_DIR from the worker for a handful of historical rows.
			return repo.MarkVoiceNoteTranscriptionFailed(ctx, tx, p.VoiceNoteID)
		}

		text, err := transcriber.Transcribe(ctx, file.Audio)
		if err != nil {
			if errors.Is(err, stt.ErrPermanent) {
				return repo.MarkVoiceNoteTranscriptionFailed(ctx, tx, p.VoiceNoteID)
			}
			return err // transient: let the worker's normal backoff retry
		}
		return repo.SetVoiceNoteTranscript(ctx, tx, p.VoiceNoteID, text)
	}
}
