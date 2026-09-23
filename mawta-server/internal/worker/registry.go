package worker

import (
	"context"

	"github.com/jackc/pgx/v5"

	"mawta-server/internal/config"
	"mawta-server/internal/domain"
	"mawta-server/internal/stt"
	"mawta-server/internal/worker/handlers"
)

// defaultRegistry adapts the handlers package's plain-argument functions
// (jobID, payload) to HandlerFunc. Handlers take plain arguments rather
// than a worker.Job so the handlers package never needs to import worker,
// which would otherwise cycle back through this registry.
//
// voice_note.transcribe is the first kind whose handler needs a dependency
// beyond ctx/tx/payload (an STT service) — it's built once here, not per
// job, and closed over by the plain-argument function handlers.VoiceNoteTranscribe
// returns.
func defaultRegistry(cfg config.Config) map[string]HandlerFunc {
	sttClient := stt.NewClient(cfg.OpenAIAPIKey, cfg.STTModel)
	transcribe := handlers.VoiceNoteTranscribe(sttClient)

	return map[string]HandlerFunc{
		domain.JobKindGradeRecompute: func(ctx context.Context, tx pgx.Tx, job Job) error {
			return handlers.GradeRecompute(ctx, tx, job.ID, job.Payload)
		},
		domain.JobKindVoiceNoteTranscribe: func(ctx context.Context, tx pgx.Tx, job Job) error {
			return transcribe(ctx, tx, job.ID, job.Payload)
		},
	}
}
