package handlers

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"mawta-server/internal/logging"
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
// kind that needs an external dependency.
//
// The task identity (task_id = the queue job ID, and the attempt number) is
// not a parameter here: the worker puts it in the context it hands the
// handler (logging.WithSTTTask), and the concrete stt.Client reads it back
// from that same context to attribute its usage event. A test double that
// wants to assert on the attribution can read it the same way.
func VoiceNoteTranscribe(transcriber Transcriber) func(ctx context.Context, tx pgx.Tx, jobID int64, payload []byte) error {
	return func(ctx context.Context, tx pgx.Tx, jobID int64, payload []byte) error {
		var p transcribePayload
		if err := json.Unmarshal(payload, &p); err != nil {
			return err
		}

		file, err := repo.GetVoiceNoteFile(ctx, tx, p.VoiceNoteID)
		if errors.Is(err, pgx.ErrNoRows) {
			// Discarded (soft-deleted) before the job ran. Nothing to do, so
			// the attempt is reported as skipped, not as a transcription.
			// No provider call happened, so no usage event was emitted.
			logging.ReportOutcome(ctx, logging.OutcomeSkipped, "voice_note_discarded")
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
				// The provider call happened and its usage event was already
				// logged inside Transcribe — including the cost it reported —
				// so recording the failure here cannot hide the spend. The job
				// completes (the failure is recorded on the voice note), but
				// the attempt is reported as a permanent failure, never as a
				// successful transcription.
				logging.ReportOutcome(ctx, logging.OutcomePermanentFailure, "transcription_failed")
				return repo.MarkVoiceNoteTranscriptionFailed(ctx, tx, p.VoiceNoteID)
			}
			return err // transient: let the worker's normal backoff retry
		}
		return repo.SetVoiceNoteTranscript(ctx, tx, p.VoiceNoteID, text)
	}
}

// STTTaskFrom is a tiny re-export so a handler-level test can read the task
// identity out of the context the worker built, without importing
// internal/logging for a single function.
func STTTaskFrom(ctx context.Context) (logging.STTTask, bool) {
	return logging.STTTaskFrom(ctx)
}
